"""Tests for EvidencePruner.

A repeated passage is not merely a wasted slot. It reads to the model as corroboration, so
a claim supported by one source is presented as supported by three — and the ranking cannot
notice, because every copy scores about as well as the original and they arrive adjacent.
The other failure is quieter still: an answer drawn entirely from one document cannot see
that another disagrees with it.

So these tests are about what gets discarded and what survives regardless. The one rule
with no exceptions is the last class here: the best passage the pipeline found is never
dropped by a rule about shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, QueryClass, RetrieverKind
from app.domain.errors import InvariantViolationError
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.retrieval.pruning import EvidencePruner
from app.domain.values import UntrustedText

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()

_PASSAGE = (
    "Backpropagation computes the gradient of the loss with respect to each weight by "
    "applying the chain rule backwards through every layer of the network in turn."
)
_OTHER = (
    "Photosynthesis converts light energy into chemical energy and stores it in the "
    "bonds of glucose molecules inside the chloroplast of a plant cell."
)


def _pruner(
    *,
    threshold: float = 0.8,
    per_parent: int = 2,
    per_page: int = 3,
    per_document: int = 4,
) -> EvidencePruner:
    return EvidencePruner(
        overlap_threshold=threshold,
        max_children_per_parent=per_parent,
        max_chunks_per_page=per_page,
        max_chunks_per_document=per_document,
    )


def _evidence(
    text: str = _PASSAGE,
    *,
    position: int = 0,
    document_id: uuid.UUID | None = None,
    page: int = 1,
    parent_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    chunk_type: ChunkType = ChunkType.TEXT,
    content_hash: str | None = None,
) -> Evidence:
    return Evidence(
        label=EvidenceLabel(position + 1),
        chunk=Chunk(
            id=chunk_id if chunk_id is not None else uuid.uuid4(),
            user_id=_USER_ID,
            knowledge_base_id=_KB_ID,
            document_id=document_id if document_id is not None else _DOC_ID,
            parent_chunk_id=parent_id,
            chunk_type=chunk_type,
            text=UntrustedText(text),
            token_count=max(1, len(text.split())),
            ordinal=position,
            page_start=page,
            page_end=page,
            index_version=1,
            created_at=_NOW,
            content_hash=content_hash,
        ),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=position,
        rerank_score=1.0 - position * 0.01,
    )


def _texts(kept: list[Evidence]) -> list[str]:
    return [e.chunk.text.value for e in kept]


# ---------------------------------------------------------------------------
# The same passage twice
# ---------------------------------------------------------------------------


class TestRepetition:
    def test_the_same_chunk_retrieved_twice_is_kept_once(self) -> None:
        """Dense and keyword search reaching the same passage is the ordinary case, not
        an edge one."""
        chunk_id = uuid.uuid4()
        kept = _pruner().prune(
            [
                _evidence(position=0, chunk_id=chunk_id),
                _evidence(position=1, chunk_id=chunk_id),
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 1

    def test_identical_text_under_different_ids_is_kept_once(self) -> None:
        kept = _pruner().prune(
            [_evidence(position=0), _evidence(position=1)],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 1

    def test_a_matching_content_hash_is_enough(self) -> None:
        kept = _pruner().prune(
            [
                _evidence(_PASSAGE, position=0, content_hash="abc"),
                _evidence(_OTHER, position=1, content_hash="abc"),
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 1

    def test_a_passage_quoted_inside_a_longer_one_is_redundant(self) -> None:
        """Containment rather than a symmetric score: the shorter passage adds nothing,
        and a measure dividing by the union would rate the pair low precisely because
        the longer one is longer."""
        kept = _pruner().prune(
            [
                _evidence(f"{_PASSAGE} {_OTHER}", position=0),
                _evidence(_PASSAGE, position=1),
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 1

    def test_different_passages_both_survive(self) -> None:
        kept = _pruner().prune(
            [_evidence(_PASSAGE, position=0), _evidence(_OTHER, position=1)],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 2

    def test_passages_on_the_same_subject_are_not_duplicates(self) -> None:
        """Two passages about one topic share most of their vocabulary while saying
        different things, which is why word runs are compared rather than word sets."""
        kept = _pruner().prune(
            [
                _evidence("The gradient of the loss is computed for every weight", position=0),
                _evidence("The loss gradient decides how much every weight moves", position=1),
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 2

    def test_a_child_and_the_parent_it_came_from_are_kept_once(self) -> None:
        """They say the same thing at two sizes."""
        parent_id = uuid.uuid4()
        kept = _pruner().prune(
            [
                _evidence(_PASSAGE, position=0, chunk_id=parent_id),
                _evidence(_OTHER, position=1, parent_id=parent_id),
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 1

    def test_tables_sharing_their_rows_are_kept_once(self) -> None:
        """Two tables can differ enough as prose to pass while repeating the rows that
        actually answer the question."""
        rows = "\n".join(f"row{i} | value{i} | unit{i}" for i in range(8))
        kept = _pruner().prune(
            [
                _evidence(rows, position=0, chunk_type=ChunkType.TABLE),
                _evidence(rows, position=1, chunk_type=ChunkType.TABLE),
            ],
            query_class=QueryClass.TABLE,
        )
        assert len(kept) == 1


# ---------------------------------------------------------------------------
# One source crowding out the rest
# ---------------------------------------------------------------------------


class TestDiversityCaps:
    def test_children_of_one_parent_are_capped(self) -> None:
        parent_id = uuid.uuid4()
        kept = _pruner(per_parent=2).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          parent_id=parent_id, page=i + 1)
                for i in range(5)
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 2

    def test_chunks_from_one_page_are_capped(self) -> None:
        """One verbose page matching in several places would otherwise fill the list."""
        kept = _pruner(per_page=3).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          page=7)
                for i in range(6)
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 3

    def test_chunks_from_one_document_are_capped(self) -> None:
        """The room the cap holds back is room for another document, so one has to exist."""
        other_doc = uuid.uuid4()
        kept = _pruner(per_document=4, per_page=99).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          page=i + 1)
                for i in range(9)
            ]
            + [
                _evidence("a passage from somewhere else entirely, saying other things",
                          position=9, document_id=other_doc)
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len([e for e in kept if e.chunk.document_id == _DOC_ID]) == 4
        assert len(kept) == 5

    def test_one_document_on_its_own_is_not_capped_against_itself(self) -> None:
        """Nothing is being held back for, so the cap would only be a truncation — and one
        applied before the count is chosen, so the selector never sees what it lost."""
        kept = _pruner(per_document=4, per_page=99).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          page=i + 1)
                for i in range(9)
            ],
            query_class=QueryClass.SUMMARY,
        )
        assert len(kept) == 9

    def test_a_second_document_is_not_affected_by_the_first_cap(self) -> None:
        other_doc = uuid.uuid4()
        candidates = [
            _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                      page=i + 1)
            for i in range(4)
        ] + [
            _evidence("a passage from somewhere else entirely, saying other things",
                      position=4, document_id=other_doc)
        ]
        kept = _pruner(per_document=4, per_page=99).prune(
            candidates, query_class=QueryClass.SUMMARY
        )
        assert len(kept) == 5

    def test_a_comparison_may_not_be_filled_from_one_document(self) -> None:
        """A comparison answered out of one book compares what that book says against
        what it says elsewhere, which is not the question."""
        other_doc = uuid.uuid4()
        kept = _pruner(per_document=4, per_page=99).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          page=i + 1)
                for i in range(6)
            ]
            + [
                _evidence("a passage from somewhere else entirely, saying other things",
                          position=6, document_id=other_doc)
            ],
            query_class=QueryClass.COMPARISON,
        )
        assert len([e for e in kept if e.chunk.document_id == _DOC_ID]) == 2
        assert len(kept) == 3

    def test_a_comparison_with_only_one_document_is_not_halved(self) -> None:
        """Halving here reserves half the list for a document that does not exist, and
        what survives is then exactly the class minimum — so the two passages sent are
        the two the minimum requires rather than the two the ranking argued for."""
        kept = _pruner(per_document=4, per_page=99).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          page=i + 1)
                for i in range(6)
            ],
            query_class=QueryClass.COMPARISON,
        )
        assert len(kept) == 6

    def test_an_ordinary_query_keeps_the_full_document_allowance(self) -> None:
        other_doc = uuid.uuid4()
        kept = _pruner(per_document=4, per_page=99).prune(
            [
                _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                          page=i + 1)
                for i in range(6)
            ]
            + [
                _evidence("a passage from somewhere else entirely, saying other things",
                          position=6, document_id=other_doc)
            ],
            query_class=QueryClass.DIRECT,
        )
        assert len([e for e in kept if e.chunk.document_id == _DOC_ID]) == 4
        assert len(kept) == 5


# ---------------------------------------------------------------------------
# What is never dropped
# ---------------------------------------------------------------------------


class TestTheBestPassageSurvives:
    def test_a_cap_cannot_remove_the_top_result(self) -> None:
        """Every rule here is about the shape of the list. The first passage is the best
        answer the pipeline found, and shape must not outrank it."""
        kept = _pruner(per_page=1, per_document=1, per_parent=1).prune(
            [_evidence(_PASSAGE, position=0)], query_class=QueryClass.COMPARISON
        )
        assert len(kept) == 1

    def test_the_top_result_is_first_in_the_output(self) -> None:
        first = _evidence(_PASSAGE, position=0)
        kept = _pruner().prune(
            [first, _evidence(_OTHER, position=1)], query_class=QueryClass.SUMMARY
        )
        assert kept[0].chunk.id == first.chunk.id

    def test_the_ranking_order_is_never_changed(self) -> None:
        """Reordering here would overrule the reranker, which is the one stage that looked
        at the query and the passage together."""
        candidates = [
            _evidence(f"passage number {i} about a distinct matter entirely", position=i,
                      page=i + 1)
            for i in range(4)
        ]
        kept = _pruner(per_page=99, per_document=99).prune(
            candidates, query_class=QueryClass.SUMMARY
        )
        assert _texts(kept) == _texts(candidates)


# ---------------------------------------------------------------------------
# Degenerate input and configuration
# ---------------------------------------------------------------------------


class TestDegenerateInput:
    def test_no_candidates_prune_to_nothing(self) -> None:
        assert _pruner().prune([], query_class=QueryClass.DIRECT) == []

    def test_a_single_candidate_survives(self) -> None:
        assert len(_pruner().prune([_evidence()], query_class=QueryClass.DIRECT)) == 1


class TestConfigurationBounds:
    @pytest.mark.parametrize("threshold", [-0.1, 1.1])
    def test_an_impossible_threshold_is_rejected(self, threshold: float) -> None:
        with pytest.raises(InvariantViolationError):
            _pruner(threshold=threshold)

    def test_a_cap_of_zero_is_rejected(self) -> None:
        """A cap of nothing would discard every passage after the first, which is not a
        diversity rule but an off switch with a misleading name."""
        with pytest.raises(InvariantViolationError):
            _pruner(per_page=0)
