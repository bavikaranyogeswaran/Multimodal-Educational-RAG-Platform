"""Tests for RRFusion (Reciprocal Rank Fusion).

All tests are pure-Python, no database. Coverage:
  - empty input → empty output
  - single list → order preserved, fusion_score = 1/(k+rank), labels re-assigned
  - two disjoint lists → higher-ranked item wins tie-break correctly
  - overlap → retriever kinds merged, fused score is sum of contributions
  - score formula: 1/(60+rank) for k=60
  - labels sequential from S1 after fusion
  - rank field re-assigned from 0 after fusion
  - many lists: a chunk in every list scores highest
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, RetrieverKind
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.retrieval.fusion import RRFusion
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_K = 60


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _chunk(scope: ScopeContext, chunk_id: uuid.UUID | None = None) -> Chunk:
    return Chunk(
        id=chunk_id or uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=uuid.uuid4(),
        chunk_type=ChunkType.TEXT,
        text=UntrustedText("Passage text."),
        token_count=5,
        ordinal=0,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=datetime.now(UTC),
        language="en",
    )


def _evidence(
    chunk: Chunk,
    rank: int,
    retrievers: frozenset[RetrieverKind],
    *,
    fusion_score: float | None = None,
) -> Evidence:
    return Evidence(
        label=EvidenceLabel(rank + 1),
        chunk=chunk,
        retrievers=retrievers,
        rank=rank,
        fusion_score=fusion_score,
    )


@pytest.fixture
def fuser() -> RRFusion:
    return RRFusion()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_lists_returns_empty(self, fuser: RRFusion) -> None:
        assert fuser.fuse() == []

    def test_empty_list_returns_empty(self, fuser: RRFusion) -> None:
        assert fuser.fuse([]) == []

    def test_multiple_empty_lists_return_empty(self, fuser: RRFusion) -> None:
        assert fuser.fuse([], [], []) == []


# ---------------------------------------------------------------------------
# Single list
# ---------------------------------------------------------------------------


class TestSingleList:
    def test_single_item_returned(self, fuser: RRFusion) -> None:
        scope = _scope()
        c = _chunk(scope)
        result = fuser.fuse([_evidence(c, 0, frozenset({RetrieverKind.DENSE}))])
        assert len(result) == 1

    def test_single_item_fusion_score_set(self, fuser: RRFusion) -> None:
        scope = _scope()
        c = _chunk(scope)
        result = fuser.fuse([_evidence(c, 0, frozenset({RetrieverKind.DENSE}))])
        expected = 1.0 / (_K + 0)
        assert result[0].fusion_score == pytest.approx(expected)

    def test_single_list_order_preserved(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1, c2 = _chunk(scope), _chunk(scope), _chunk(scope)
        ev = [
            _evidence(c0, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(c1, 1, frozenset({RetrieverKind.DENSE})),
            _evidence(c2, 2, frozenset({RetrieverKind.DENSE})),
        ]
        result = fuser.fuse(ev)
        assert [r.chunk.id for r in result] == [c0.id, c1.id, c2.id]

    def test_labels_reassigned_from_s1(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1 = _chunk(scope), _chunk(scope)
        result = fuser.fuse([
            _evidence(c0, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(c1, 1, frozenset({RetrieverKind.DENSE})),
        ])
        assert [r.label.number for r in result] == [1, 2]

    def test_ranks_reassigned_from_zero(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1 = _chunk(scope), _chunk(scope)
        result = fuser.fuse([
            _evidence(c0, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(c1, 1, frozenset({RetrieverKind.DENSE})),
        ])
        assert [r.rank for r in result] == [0, 1]

    def test_score_formula_k60(self, fuser: RRFusion) -> None:
        scope = _scope()
        chunks = [_chunk(scope) for _ in range(3)]
        ev = [_evidence(c, i, frozenset({RetrieverKind.KEYWORD})) for i, c in enumerate(chunks)]
        result = fuser.fuse(ev)
        for i, r in enumerate(result):
            assert r.fusion_score == pytest.approx(1.0 / (_K + i))


# ---------------------------------------------------------------------------
# Two disjoint lists
# ---------------------------------------------------------------------------


class TestDisjointLists:
    def test_all_chunks_included(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1 = _chunk(scope), _chunk(scope)
        dense = [_evidence(c0, 0, frozenset({RetrieverKind.DENSE}))]
        keyword = [_evidence(c1, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        ids = {r.chunk.id for r in result}
        assert ids == {c0.id, c1.id}

    def test_tied_chunks_have_equal_scores(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1 = _chunk(scope), _chunk(scope)
        dense = [_evidence(c0, 0, frozenset({RetrieverKind.DENSE}))]
        keyword = [_evidence(c1, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        assert result[0].fusion_score == pytest.approx(result[1].fusion_score)

    def test_better_ranked_chunk_wins_when_unequal(self, fuser: RRFusion) -> None:
        scope = _scope()
        c_best, c_worse = _chunk(scope), _chunk(scope)
        # c_best is rank 0 in dense, c_worse is rank 1 in keyword (both single lists)
        dense = [_evidence(c_best, 0, frozenset({RetrieverKind.DENSE}))]
        keyword = [_evidence(c_worse, 1, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        assert result[0].chunk.id == c_best.id

    def test_retriever_kind_reflects_source(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1 = _chunk(scope), _chunk(scope)
        dense = [_evidence(c0, 0, frozenset({RetrieverKind.DENSE}))]
        keyword = [_evidence(c1, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        by_id = {r.chunk.id: r for r in result}
        assert by_id[c0.id].retrievers == frozenset({RetrieverKind.DENSE})
        assert by_id[c1.id].retrievers == frozenset({RetrieverKind.KEYWORD})


# ---------------------------------------------------------------------------
# Overlapping lists (same chunk in multiple)
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_overlapping_chunk_ranks_first(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared, unique = _chunk(scope), _chunk(scope)
        dense = [
            _evidence(shared, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(unique, 1, frozenset({RetrieverKind.DENSE})),
        ]
        keyword = [_evidence(shared, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        assert result[0].chunk.id == shared.id

    def test_overlapping_chunk_fuses_retriever_kinds(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared = _chunk(scope)
        dense = [_evidence(shared, 0, frozenset({RetrieverKind.DENSE}))]
        keyword = [_evidence(shared, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        assert result[0].retrievers == frozenset({RetrieverKind.DENSE, RetrieverKind.KEYWORD})

    def test_overlapping_chunk_score_is_sum(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared = _chunk(scope)
        dense = [_evidence(shared, 0, frozenset({RetrieverKind.DENSE}))]
        keyword = [_evidence(shared, 2, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        expected = 1.0 / (_K + 0) + 1.0 / (_K + 2)
        assert result[0].fusion_score == pytest.approx(expected)

    def test_non_overlapping_chunk_has_single_contribution(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared, unique = _chunk(scope), _chunk(scope)
        dense = [
            _evidence(shared, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(unique, 1, frozenset({RetrieverKind.DENSE})),
        ]
        keyword = [_evidence(shared, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        by_id = {r.chunk.id: r for r in result}
        assert by_id[unique.id].fusion_score == pytest.approx(1.0 / (_K + 1))

    def test_result_length_equals_unique_chunks(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared, a, b = _chunk(scope), _chunk(scope), _chunk(scope)
        dense = [
            _evidence(shared, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(a, 1, frozenset({RetrieverKind.DENSE})),
        ]
        keyword = [
            _evidence(shared, 0, frozenset({RetrieverKind.KEYWORD})),
            _evidence(b, 1, frozenset({RetrieverKind.KEYWORD})),
        ]
        result = fuser.fuse(dense, keyword)
        assert len(result) == 3  # shared, a, b

    def test_three_lists_overlap_scores_sum_all_contributions(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared = _chunk(scope)
        ev_d = _evidence(shared, 0, frozenset({RetrieverKind.DENSE}))
        ev_k = _evidence(shared, 1, frozenset({RetrieverKind.KEYWORD}))
        ev_g = _evidence(shared, 0, frozenset({RetrieverKind.GRAPH}))
        result = fuser.fuse([ev_d], [ev_k], [ev_g])
        expected = 1.0 / (_K + 0) + 1.0 / (_K + 1) + 1.0 / (_K + 0)
        assert result[0].fusion_score == pytest.approx(expected)

    def test_three_lists_overlap_merges_all_retriever_kinds(self, fuser: RRFusion) -> None:
        scope = _scope()
        shared = _chunk(scope)
        ev_d = _evidence(shared, 0, frozenset({RetrieverKind.DENSE}))
        ev_k = _evidence(shared, 0, frozenset({RetrieverKind.KEYWORD}))
        ev_g = _evidence(shared, 0, frozenset({RetrieverKind.GRAPH}))
        result = fuser.fuse([ev_d], [ev_k], [ev_g])
        assert result[0].retrievers == frozenset(
            {RetrieverKind.DENSE, RetrieverKind.KEYWORD, RetrieverKind.GRAPH}
        )


# ---------------------------------------------------------------------------
# Output ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_output_sorted_by_fusion_score_descending(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1, c2 = _chunk(scope), _chunk(scope), _chunk(scope)
        # rank 0 → score 1/60, rank 1 → 1/61, rank 2 → 1/62
        dense = [
            _evidence(c0, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(c1, 1, frozenset({RetrieverKind.DENSE})),
            _evidence(c2, 2, frozenset({RetrieverKind.DENSE})),
        ]
        result = fuser.fuse(dense)
        scores = [r.fusion_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_labels_sequential_after_sort(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1, c2 = _chunk(scope), _chunk(scope), _chunk(scope)
        dense = [
            _evidence(c0, 0, frozenset({RetrieverKind.DENSE})),
            _evidence(c1, 1, frozenset({RetrieverKind.DENSE})),
        ]
        keyword = [_evidence(c2, 0, frozenset({RetrieverKind.KEYWORD}))]
        result = fuser.fuse(dense, keyword)
        assert [r.label.number for r in result] == list(range(1, len(result) + 1))

    def test_ranks_sequential_after_sort(self, fuser: RRFusion) -> None:
        scope = _scope()
        c0, c1 = _chunk(scope), _chunk(scope)
        result = fuser.fuse(
            [_evidence(c0, 0, frozenset({RetrieverKind.DENSE}))],
            [_evidence(c1, 0, frozenset({RetrieverKind.KEYWORD}))],
        )
        assert [r.rank for r in result] == list(range(len(result)))
