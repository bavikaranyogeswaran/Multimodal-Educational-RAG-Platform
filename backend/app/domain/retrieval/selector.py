"""Decide how many of the ranked passages actually reach the model.

Sending a fixed number is wrong in both directions and wrong quietly. A question answered
by one sentence gets four more passages that dilute it, and the model, given material, uses
it — so the answer drifts toward whatever the extra passages happened to say. A comparison
gets the same four and has no room for the second subject, so it compares one thing against
nothing and says so fluently. Neither failure looks like a retrieval failure afterwards:
the passages were all plausibly relevant, and the ranking was correct.

So the count comes from what the question needs. A direct factual question wants the
passage that states the fact; a comparison cannot be answered from fewer than two sources;
a concept map is broad by nature. Those are properties of the question, decided before
retrieval by the classifier, which is why the range is looked up rather than guessed.

Three limits then argue with each other, and the order they win in is the substance of this
module:

The token budget wins over everything. Passages beyond it are not sent anywhere — they are
truncated by the model, silently, from the end.

The class minimum wins over the score margin. The margin says what the ranking believes;
the minimum says what the question requires. A comparison whose second source scored poorly
is still a comparison, and answering it from one source produces a confident half-answer,
where sending the weak second lets the model say the sources only cover one side.

One passage wins over the class minimum. Evidence that fell below every threshold is still
better than none, and an empty prompt cannot be grounded at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from app.domain.enums import QueryClass
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_positive
from app.domain.retrieval.entities import Evidence, EvidenceLabel


@dataclass(frozen=True, slots=True)
class CountRange:
    """How many passages a kind of question is worth answering with."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        require_positive(self.minimum, "CountRange.minimum")
        if self.maximum < self.minimum:
            raise InvariantViolationError(
                f"CountRange maximum ({self.maximum}) is below minimum ({self.minimum})"
            )

    def clamped_to(self, *, floor: int, ceiling: int) -> CountRange:
        """The range as it applies once the global bounds are taken into account.

        The ceiling is absolute and wins over everything: it is the limit on what any
        ordinary query may send, so a class asking for more collapses onto it rather than
        raising it. A class wanting three passages under a ceiling of two gets two.
        """
        high = min(self.maximum, ceiling)
        low = min(max(self.minimum, floor), high)
        return CountRange(minimum=low, maximum=high)


#: What each kind of question is worth answering with, before the global bounds apply.
#:
#: A rule about questions rather than a tuning knob, which is why it lives here and not in
#: configuration: promoting twenty-six numbers to environment variables would make the rule
#: unreadable and calibrate nothing, since none of them can be calibrated until there is an
#: evaluation set. Any single range that later needs calibrating can be lifted out on its
#: own.
_DEFAULT_RANGES: Mapping[QueryClass, CountRange] = {
    # Every question no rule recognised arrives here, so this is the budget for a question
    # nobody has read rather than for a known simple one. A fact stated in one passage is
    # still answered from one, because the minimum stays at one and the score margin stops
    # as soon as the ranking falls away — the ceiling only decides how far it may read when
    # the ranking keeps saying yes. It sits above the tightest classes because what lands
    # here in practice is not simple: a procedure and a "what X are used" aggregation both
    # fall through, and both were being answered from two passages.
    QueryClass.DIRECT: CountRange(1, 4),
    # A definition, and where the term is actually used.
    QueryClass.EXACT_TERM: CountRange(1, 3),
    # The table, and whatever names its columns.
    QueryClass.TABLE: CountRange(1, 3),
    # The figure, its caption, and the passage that explains it.
    QueryClass.VISUAL: CountRange(1, 3),
    # A relationship needs both of its ends present.
    QueryClass.RELATIONSHIP: CountRange(2, 5),
    QueryClass.PREREQUISITE: CountRange(2, 5),
    # Cannot be answered from one source without comparing something against nothing.
    QueryClass.COMPARISON: CountRange(2, 5),
    # Broad by nature: a map of one node is not a map.
    QueryClass.CONCEPT_MAP: CountRange(3, 8),
    QueryClass.MULTI_DOCUMENT: CountRange(3, 8),
    QueryClass.AGGREGATION: CountRange(3, 8),
    QueryClass.SUMMARY: CountRange(3, 8),
    QueryClass.QUIZ_GENERATION: CountRange(3, 8),
    # Wide until sub-question coverage decides it, which is a later phase's work.
    QueryClass.MULTI_HOP: CountRange(2, 8),
}

#: Sent when the ranking has nothing to say about a class, which should not happen while
#: every class is listed above, but is preferable to failing a query over a missing key.
_FALLBACK_RANGE = CountRange(1, 3)


class EvidenceSelector:
    """Choose the passages that will be shown to the model, and number them."""

    def __init__(
        self,
        count_tokens: Callable[[str], int],
        *,
        min_items: int,
        max_items: int,
        relative_score_margin: float,
        token_budget: int,
        ranges: Mapping[QueryClass, CountRange] | None = None,
    ) -> None:
        require_positive(min_items, "min_items")
        require_positive(max_items, "max_items")
        require_positive(token_budget, "token_budget")
        if max_items < min_items:
            raise InvariantViolationError("max_items must not be below min_items")
        if relative_score_margin < 0:
            raise InvariantViolationError("relative_score_margin must not be negative")

        self._count = count_tokens
        self._min_items = min_items
        self._max_items = max_items
        self._margin = relative_score_margin
        self._budget = token_budget
        self._ranges = dict(ranges) if ranges is not None else dict(_DEFAULT_RANGES)

    def select(
        self, candidates: Sequence[Evidence], *, query_class: QueryClass
    ) -> list[Evidence]:
        """The passages worth sending, in order, renumbered from one.

        Candidates arrive in the order the reranker put them and that order is taken as
        authoritative — this decides how far down the list to read, never how to sort it.
        """
        if not candidates:
            return []

        allowed = self._ranges.get(query_class, _FALLBACK_RANGE).clamped_to(
            floor=self._min_items, ceiling=self._max_items
        )
        cutoff = self._cutoff(candidates)

        kept: list[Evidence] = []
        spent = 0
        for candidate in candidates:
            if len(kept) >= allowed.maximum:
                break

            cost = self._count(candidate.chunk.text.value)
            # The first passage is admitted whatever it costs. Refusing it on budget
            # would leave nothing to answer from, and a prompt with no evidence is a
            # question the model answers from memory.
            if kept and spent + cost > self._budget:
                break

            below_the_margin = (
                cutoff is not None
                and candidate.rerank_score is not None
                and candidate.rerank_score < cutoff
            )
            if below_the_margin and len(kept) >= allowed.minimum:
                break

            kept.append(candidate)
            spent += cost

        return [
            replace(evidence, label=EvidenceLabel(position + 1), rank=position)
            for position, evidence in enumerate(kept)
        ]

    # -----------------------------------------------------------------------

    def _cutoff(self, candidates: Sequence[Evidence]) -> float | None:
        """The score below which a passage is judged too far behind the best one.

        Relative to the top score rather than absolute. Cross-encoder scores are not
        calibrated across queries — a strongly relevant pair can score below zero — so any
        fixed cutoff either keeps everything or discards everything depending on the
        question.
        """
        top = candidates[0].rerank_score
        if top is None:
            return None
        return top - abs(top) * self._margin
