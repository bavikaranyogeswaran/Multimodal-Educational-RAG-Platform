"""Drop the passages that add nothing before deciding how many to send.

Two different things crowd an evidence list, and both look like relevance from inside the
ranking. The first is repetition: the same passage found by two retrievers, a child and the
parent it was cut from, a table whose rows appear again in a neighbouring chunk. Every copy
scores about as well as the original, so they arrive adjacent and the list says the same
thing three times. The second is concentration: one verbose page, or one document, that
matches the query in enough places to fill the list on its own, leaving the answer sourced
from a single spot in a single book.

Both are worse than they look. A repeated passage does not merely waste a slot — it reads
to the model as corroboration, so a claim supported once is presented as supported three
times. And an answer drawn wholly from one document cannot notice that another disagrees.

So this runs before the count is chosen rather than after. Selecting five passages and then
discovering three were duplicates would leave two, having spent the budget on the copies;
pruning first means the count is chosen over passages that are all still saying something.

The highest-ranked passage is never dropped, by any rule here. It is the best answer the
whole pipeline found, and a diversity rule that can discard it has optimised the shape of
the evidence list over its content.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, QueryClass
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_positive
from app.domain.retrieval.entities import Evidence

#: Length of the word runs compared when asking whether two passages are the same. Long
#: enough that ordinary shared phrasing does not match, short enough that a sentence
#: reworded at one end still does.
_SHINGLE = 5


@dataclass
class _Counts:
    """How much of the list each source has taken so far."""

    parents: dict[object, int] = field(default_factory=dict)
    pages: dict[tuple[object, int], int] = field(default_factory=dict)
    documents: dict[object, int] = field(default_factory=dict)

    def admit(self, evidence: Evidence) -> None:
        chunk = evidence.chunk
        # A parent of None is every unparented chunk at once, so it is not counted:
        # capping it would cap chunks that share nothing but the absence of a parent.
        if chunk.parent_chunk_id is not None:
            self.parents[chunk.parent_chunk_id] = self.parents.get(chunk.parent_chunk_id, 0) + 1
        page = _page_of(chunk)
        self.pages[page] = self.pages.get(page, 0) + 1
        self.documents[chunk.document_id] = self.documents.get(chunk.document_id, 0) + 1


@dataclass(frozen=True, slots=True)
class _Kept:
    """A passage already admitted, with what later ones are compared against."""

    evidence: Evidence
    shingles: frozenset[tuple[str, ...]]
    lines: frozenset[str]


class EvidencePruner:
    """Remove what repeats, and cap what crowds out everything else."""

    def __init__(
        self,
        *,
        overlap_threshold: float,
        max_children_per_parent: int,
        max_chunks_per_page: int,
        max_chunks_per_document: int,
    ) -> None:
        if not 0.0 <= overlap_threshold <= 1.0:
            raise InvariantViolationError("overlap_threshold must be between 0 and 1")
        require_positive(max_children_per_parent, "max_children_per_parent")
        require_positive(max_chunks_per_page, "max_chunks_per_page")
        require_positive(max_chunks_per_document, "max_chunks_per_document")

        self._threshold = overlap_threshold
        self._max_per_parent = max_children_per_parent
        self._max_per_page = max_chunks_per_page
        self._max_per_document = max_chunks_per_document

    def prune(
        self, candidates: Sequence[Evidence], *, query_class: QueryClass
    ) -> list[Evidence]:
        """The candidates worth keeping, in the order they arrived.

        Order is preserved exactly: this decides what to discard, never what to promote.
        Reordering here would silently overrule the reranker, which is the one stage that
        looked at the query and the passage together.
        """
        if not candidates:
            return []

        per_document = self._document_cap(query_class)
        counts = _Counts()

        # The best passage the pipeline found is admitted outright, before any rule is
        # consulted. Written as the shape of the loop rather than as a condition inside
        # it, so that no rule added later can quietly acquire the power to drop it.
        best, rest = candidates[0], candidates[1:]
        kept: list[_Kept] = [_entry(best)]
        counts.admit(best)

        for candidate in rest:
            chunk = candidate.chunk
            if self._repeats(candidate, kept):
                continue
            if counts.parents.get(chunk.parent_chunk_id, 0) >= self._max_per_parent:
                continue
            if counts.pages.get(_page_of(chunk), 0) >= self._max_per_page:
                continue
            if counts.documents.get(chunk.document_id, 0) >= per_document:
                continue

            kept.append(_entry(candidate))
            counts.admit(candidate)

        return [entry.evidence for entry in kept]

    # -----------------------------------------------------------------------

    def _document_cap(self, query_class: QueryClass) -> int:
        """How much of the evidence one document may supply.

        Halved for comparisons. A comparison answered entirely out of one book compares
        what that book says against what it says elsewhere, which is not the question —
        so no single document may fill more than half the list, and where a second
        document has anything relevant it gets in.
        """
        if query_class is QueryClass.COMPARISON:
            return max(1, self._max_per_document // 2)
        return self._max_per_document

    def _repeats(self, candidate: Evidence, kept: Sequence[_Kept]) -> bool:
        """Whether this passage is one already admitted, in any of the ways it can be."""
        chunk = candidate.chunk
        shingles = _shingles(chunk.text.value)
        lines = _lines(chunk.text.value)

        for entry in kept:
            other = entry.evidence.chunk

            # The same row twice over, which two retrievers reaching the same passage
            # produce as readily as one document repeating itself.
            if chunk.id == other.id:
                return True
            if chunk.content_hash is not None and chunk.content_hash == other.content_hash:
                return True

            # A child and the section it was cut from say the same thing at two sizes.
            if chunk.parent_chunk_id == other.id or other.parent_chunk_id == chunk.id:
                return True

            if _containment(shingles, entry.shingles) >= self._threshold:
                return True

            # Tables are compared by their rows as well. Two tables can share the rows
            # that matter while differing enough elsewhere to pass as distinct prose.
            both_tables = (
                chunk.chunk_type is ChunkType.TABLE and other.chunk_type is ChunkType.TABLE
            )
            if both_tables and _containment(lines, entry.lines) >= self._threshold:
                return True

        return False


# ---------------------------------------------------------------------------
# Comparing passages
# ---------------------------------------------------------------------------


def _normalised(text: str) -> str:
    """Words in order, case and whitespace flattened.

    Enough for the question being asked. Two passages differing only in line wrapping or
    capitalisation are the same evidence, and stemming them further would start matching
    passages that merely discuss the same topic.
    """
    return " ".join(text.lower().split())


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    """Overlapping runs of words, which is what gets compared.

    Word runs rather than a bag of words: two passages about the same subject share most
    of their vocabulary while saying different things, and only repetition shares the
    order as well.
    """
    words = _normalised(text).split()
    if not words:
        return frozenset()
    if len(words) <= _SHINGLE:
        return frozenset({tuple(words)})
    return frozenset(
        tuple(words[i : i + _SHINGLE]) for i in range(len(words) - _SHINGLE + 1)
    )


def _lines(text: str) -> frozenset[str]:
    """The rows of a table, normalised, for comparing tables to each other."""
    return frozenset(_normalised(line) for line in text.splitlines() if line.strip())


def _containment(smaller: frozenset[object], larger: frozenset[object]) -> float:
    """How much of the shorter passage sits inside the longer one.

    Containment rather than a symmetric similarity: a paragraph quoted whole inside a
    section is entirely redundant with it, and a measure that divided by the union would
    score that pair low precisely because the section is longer.
    """
    if not smaller or not larger:
        return 0.0
    return len(smaller & larger) / min(len(smaller), len(larger))


def _page_of(chunk: Chunk) -> tuple[object, int]:
    """Which page a passage counts against.

    Its first, even where it runs onto the next. A chunk spanning a break belongs to
    both and counting it twice would let a page reach its cap without contributing that
    much of the answer.
    """
    return (chunk.document_id, chunk.page_start)


def _entry(evidence: Evidence) -> _Kept:
    text = evidence.chunk.text.value
    return _Kept(evidence=evidence, shingles=_shingles(text), lines=_lines(text))
