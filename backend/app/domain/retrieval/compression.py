"""Cut selected passages down to what will fit, without changing what they say.

Everything upstream has decided which passages answer the question. They can still be too
much text: a parent loaded because its child was a fragment brings a whole section with it,
and eight of those do not fit beside the instructions, the history and the question.

Something has to go, and there are two ways to shorten a passage. Asking a model to
summarise it produces something shorter and fluent that no longer says quite what the
source said — numbers drift, hedges disappear, and the citation now points at text that
does not contain the claim. Selecting whole sentences out of the original produces
something that is, word for word, in the document. Only the second can be cited, so it is
the only one used; generative compression exists behind a flag that is off.

Which sentences go is the whole risk. A sentence carrying a negation, a number, or a
condition is exactly the sentence whose loss changes an answer rather than shortening it —
drop "the method does not converge for non-convex losses" and what remains reads as an
unqualified endorsement, fluently and with a citation. So those sentences are kept whatever
they score, and only ordinary prose competes for the space that is left.

Structured content is not compressed by sentence at all. A formula is one thing, a caption
is already short, and a table is rows: cutting a table by sentence would take its headers
away and leave numbers in unnamed columns.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace

from app.domain.enums import ChunkType
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_positive
from app.domain.retrieval.entities import Evidence
from app.domain.sentences import split_sentences
from app.domain.values import UntrustedText

#: Words that reverse or restrict a claim. A passage that loses one of these does not say
#: less than it did — it says something else.
_NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "cannot",
        "neither",
        "nor",
        "without",
        "none",
        "nothing",
        "unable",
        "fails",
        "except",
    }
)

#: Words that attach a condition or a limit to a claim, which is the other way a sentence
#: can be load-bearing without containing a number.
_QUALIFIERS = frozenset(
    {
        "if",
        "unless",
        "only",
        "provided",
        "assuming",
        "requires",
        "must",
        "always",
        "approximately",
        "roughly",
        "least",
        "most",
        "before",
        "after",
        "when",
    }
)

#: Any digit at all. Numbers carry their units with them in the same sentence, so keeping
#: the sentence keeps both, and there is no need to recognise a unit as such.
_DIGIT = re.compile(r"\d")

#: Contractions that hide a negation inside a word rather than beside it.
_CONTRACTED_NEGATION = re.compile(r"\b\w+n[\u2019']t\b", re.IGNORECASE)

_WORD = re.compile(r"[a-z0-9]+")

#: Content that is not prose and cannot be cut by sentence. A table becomes rows in
#: unnamed columns; a formula or a caption is one indivisible thing.
_STRUCTURED = frozenset(
    {
        ChunkType.TABLE,
        ChunkType.FORMULA,
        ChunkType.FIGURE,
        ChunkType.CHART,
        ChunkType.DIAGRAM,
    }
)


class EvidenceCompressor:
    """Fit the selected passages into the space available for them."""

    def __init__(
        self,
        count_tokens: Callable[[str], int],
        *,
        token_budget: int,
        generative_enabled: bool = False,
    ) -> None:
        require_positive(token_budget, "token_budget")
        if generative_enabled:
            raise InvariantViolationError(
                "generative compression is not implemented, and the flag exists to record "
                "that it is deliberately off: a summarised passage is no longer text the "
                "citation points at"
            )
        self._count = count_tokens
        self._budget = token_budget

    def compress(self, evidence: Sequence[Evidence], *, query: str) -> list[Evidence]:
        """The same passages, shortened only where they do not fit.

        Each passage is offered an equal share of what the ones before it left, so a short
        passage hands its unused room to those after it and the highest-ranked passage has
        first call on the whole budget. A passage already inside its share is returned
        untouched: shortening it could only lose something and would save nothing.
        """
        if not evidence:
            return []

        terms = _terms(query)
        remaining = self._budget
        result: list[Evidence] = []

        for position, item in enumerate(evidence):
            share = max(1, remaining // (len(evidence) - position))
            cost = self._count(item.chunk.text.value)
            if cost <= share:
                result.append(item)
                remaining -= cost
                continue

            shortened = self._shorten(item, terms=terms, share=share)
            result.append(shortened)
            remaining -= self._count(shortened.chunk.text.value)

        return result

    # -----------------------------------------------------------------------

    def _shorten(self, item: Evidence, *, terms: frozenset[str], share: int) -> Evidence:
        chunk = item.chunk
        if chunk.chunk_type is ChunkType.TABLE:
            text = self._select_rows(chunk.text.value, terms=terms, share=share)
        elif chunk.chunk_type in _STRUCTURED:
            # A formula and a caption are each one thing. Shortening them means removing
            # part of the thing, so an oversized one is sent whole and the passages after
            # it get less room.
            return item
        else:
            text = self._select_sentences(chunk.text.value, terms=terms, share=share)

        if not text or text == chunk.text.value:
            return item
        return replace(item, chunk=chunk.with_compressed_text(UntrustedText(text)), compressed=True)

    def _select_sentences(self, text: str, *, terms: frozenset[str], share: int) -> str:
        """Keep what the answer needs, in the order the passage said it.

        Sentences that must be kept are taken first and are never traded away for space.
        Where they alone exceed the share the passage stays over budget, because a passage
        that fits and misleads is worse than one that is longer than planned.
        """
        sentences = split_sentences(text)
        if len(sentences) <= 1:
            return text

        required = {i for i, s in enumerate(sentences) if _load_bearing(s)}
        optional = sorted(
            (i for i in range(len(sentences)) if i not in required),
            key=lambda i: (-_overlap(sentences[i], terms), i),
        )

        chosen = set(required)
        for index in optional:
            candidate = chosen | {index}
            if self._count(_join(sentences, candidate)) > share and chosen:
                continue
            chosen = candidate

        return _join(sentences, chosen) if chosen else text

    def _select_rows(self, text: str, *, terms: frozenset[str], share: int) -> str:
        """Keep the title, the headers and the rows that were asked about.

        The opening lines are kept unconditionally. In a table chunk they are the caption
        and the column headings, and without them the rows are numbers in unnamed columns
        — which is worse than an oversized table, because it is confidently wrong rather
        than merely long.
        """
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) <= _TABLE_PREAMBLE + 1:
            return text

        kept = list(range(min(_TABLE_PREAMBLE, len(lines))))
        rest = sorted(
            range(len(kept), len(lines)),
            key=lambda i: (-_overlap(lines[i], terms), i),
        )
        for index in rest:
            candidate = sorted([*kept, index])
            if self._count("\n".join(lines[i] for i in candidate)) > share and kept:
                continue
            kept = candidate

        return "\n".join(lines[i] for i in sorted(kept))


#: How many opening lines of a table are its title and headings rather than its data.
_TABLE_PREAMBLE = 2


def _load_bearing(sentence: str) -> bool:
    """Whether losing this sentence would change the claim rather than shorten it."""
    if _DIGIT.search(sentence) or _CONTRACTED_NEGATION.search(sentence):
        return True
    words = frozenset(_WORD.findall(sentence.lower()))
    return bool(words & _NEGATIONS) or bool(words & _QUALIFIERS)


def _overlap(sentence: str, terms: frozenset[str]) -> int:
    """How much of the question this sentence actually addresses."""
    if not terms:
        return 0
    return len(frozenset(_WORD.findall(sentence.lower())) & terms)


def _terms(query: str) -> frozenset[str]:
    return frozenset(_WORD.findall(query.lower()))


def _join(sentences: Sequence[str], chosen: set[int]) -> str:
    return " ".join(sentences[i] for i in sorted(chosen))
