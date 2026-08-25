"""A question whose answer is known, and where it is known to be.

The point of a gold pair is to be able to say whether a retrieval change helped, rather
than reading one answer and forming an impression. Everything here exists to make that
judgement reproducible: the same questions, the same expected locations, run again after
a change and compared.

**Answers are located by page, not by chunk.** The plan asked for gold chunk ids, and
they cannot be used: the parser mints new identifiers on every read, so a set keyed on
chunk ids would be invalidated by the next re-ingestion and would silently score zero
rather than fail. Pages come from the file, survive a rebuild, and are also what a
student is actually sent to. `must_contain` narrows further where a page holds more than
one thing worth finding.

A gold pair is a claim about the *material*, not about the current index. That is what
lets the same set score two different chunking strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import QueryClass
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_non_blank


@dataclass(frozen=True)
class GoldPair:
    """One question, and the pages that answer it."""

    #: Stable across edits to the question, so a score can be traced to the same pair
    #: after rewording. Human-readable rather than a UUID, because these are read.
    id: str

    #: Phrased as a student would ask it, which is the whole difficulty. A question
    #: written by looking at a passage inherits that passage's vocabulary, and retrieval
    #: then finds it for reasons that have nothing to do with being good at retrieval.
    question: str

    #: What the classifier is expected to make of it. Recorded as part of the pair rather
    #: than derived, so a rule change that reclassifies a question shows up as a
    #: disagreement instead of quietly moving the evidence budget underneath it.
    expected_class: QueryClass

    #: The filename the answer lives in, not a document id — ids are re-minted on every
    #: upload, and the point of this file is to outlive the index.
    document: str

    #: Every page a complete answer needs. One page for a fact; several for a procedure
    #: that spans a section, or a comparison that reads two places at once.
    gold_pages: frozenset[int]

    #: Text a correct passage carries, for pages that hold more than one thing worth
    #: finding. Matched case-insensitively, and each string must appear somewhere in the
    #: retrieved set for the pair to count as fully answered.
    must_contain: tuple[str, ...] = ()

    #: Why these pages and not others. Written for whoever disagrees with the labelling
    #: later, which is the person this file is really for.
    note: str = ""

    #: Marks a pair whose answer is not in the material at all. Retrieval finding nothing
    #: is the correct outcome, and a set with none of these cannot tell a system that
    #: abstains properly from one that never abstains.
    unanswerable: bool = field(default=False)

    def __post_init__(self) -> None:
        require_non_blank(self.id, "GoldPair.id")
        require_non_blank(self.question, "GoldPair.question")
        require_non_blank(self.document, "GoldPair.document")

        if self.unanswerable:
            if self.gold_pages:
                raise InvariantViolationError(
                    f"GoldPair {self.id} is marked unanswerable but names gold pages — "
                    "a question the material does not answer has nowhere to be right"
                )
            return

        if not self.gold_pages:
            raise InvariantViolationError(
                f"GoldPair {self.id} names no gold pages. A pair that cannot say where "
                "the answer is scores every retrieval identically and measures nothing"
            )
        for page in self.gold_pages:
            if page < 1:
                raise InvariantViolationError(
                    f"GoldPair {self.id} names page {page}; pages are numbered from 1"
                )


@dataclass(frozen=True)
class GoldSet:
    """The pairs, and what they were written against."""

    pairs: tuple[GoldPair, ...]

    #: The book, edition and page count the pages refer to. A gold set is meaningless
    #: against a different file, and the failure mode is silent — every page number still
    #: resolves, to the wrong content.
    source: str

    def __post_init__(self) -> None:
        require_non_blank(self.source, "GoldSet.source")
        if not self.pairs:
            raise InvariantViolationError("A GoldSet with no pairs measures nothing")
        seen: set[str] = set()
        for pair in self.pairs:
            if pair.id in seen:
                raise InvariantViolationError(
                    f"Duplicate GoldPair id {pair.id!r} — scores are reported per pair "
                    "and two pairs sharing an id cannot both be read"
                )
            seen.add(pair.id)

    @property
    def answerable(self) -> tuple[GoldPair, ...]:
        return tuple(pair for pair in self.pairs if not pair.unanswerable)

    def by_class(self, query_class: QueryClass) -> tuple[GoldPair, ...]:
        return tuple(pair for pair in self.pairs if pair.expected_class is query_class)

    @property
    def classes_covered(self) -> frozenset[QueryClass]:
        """Which query classes have at least one pair.

        A set that covers eleven of thirteen classes still reports a single overall
        number, and that number says nothing about the two it never asked about.
        """
        return frozenset(pair.expected_class for pair in self.pairs)
