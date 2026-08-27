"""Tests for EvidenceSelector."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.application.queries.coverage_classifier import SubQuestionCoverage
from app.application.queries.evidence_selector import EvidenceSelector, SubQuestionEvidence
from app.domain.enums import CoverageStatus
from app.domain.retrieval.decomposition import SubQuestion


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sq(sq_id: str) -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _evidence(chunk_id: uuid.UUID | None = None) -> MagicMock:
    ev = MagicMock()
    ev.chunk = MagicMock()
    ev.chunk.id = chunk_id if chunk_id is not None else uuid.uuid4()
    return ev


def _coverage(
    sq_id: str,
    status: CoverageStatus,
    evidence: list | None = None,
) -> SubQuestionCoverage:
    return SubQuestionCoverage(
        sub_question=_sq(sq_id),
        evidence=evidence or [],
        coverage=status,
    )


# ---------------------------------------------------------------------------
# constructor validation
# ---------------------------------------------------------------------------


class TestEvidenceSelectorConstructor:
    def test_max_per_sub_question_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            EvidenceSelector(max_per_sub_question=0)

    def test_max_per_sub_question_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            EvidenceSelector(max_per_sub_question=-1)

    def test_valid_max(self) -> None:
        sel = EvidenceSelector(max_per_sub_question=1)
        assert sel is not None


# ---------------------------------------------------------------------------
# empty / trivial cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_input_returns_empty(self) -> None:
        assert EvidenceSelector().select([]) == []

    def test_sub_question_with_no_evidence_yields_empty_tuple(self) -> None:
        sel = EvidenceSelector()
        results = sel.select([_coverage("Q1", CoverageStatus.UNSUPPORTED, evidence=[])])
        assert results[0].evidence == ()

    def test_evidence_below_cap_all_kept(self) -> None:
        ev1, ev2 = _evidence(), _evidence()
        sel = EvidenceSelector(max_per_sub_question=5)
        results = sel.select([_coverage("Q1", CoverageStatus.SUPPORTED, [ev1, ev2])])
        assert ev1 in results[0].evidence
        assert ev2 in results[0].evidence

    def test_evidence_exactly_at_cap_all_kept(self) -> None:
        evs = [_evidence() for _ in range(3)]
        sel = EvidenceSelector(max_per_sub_question=3)
        results = sel.select([_coverage("Q1", CoverageStatus.SUPPORTED, evs)])
        assert len(results[0].evidence) == 3


# ---------------------------------------------------------------------------
# cap enforcement
# ---------------------------------------------------------------------------


class TestCapEnforcement:
    def test_evidence_above_cap_truncated(self) -> None:
        evs = [_evidence() for _ in range(8)]
        sel = EvidenceSelector(max_per_sub_question=3)
        results = sel.select([_coverage("Q1", CoverageStatus.SUPPORTED, evs)])
        assert len(results[0].evidence) == 3

    def test_cap_one_returns_single_item(self) -> None:
        evs = [_evidence() for _ in range(5)]
        sel = EvidenceSelector(max_per_sub_question=1)
        results = sel.select([_coverage("Q1", CoverageStatus.SUPPORTED, evs)])
        assert len(results[0].evidence) == 1

    def test_cap_applied_per_sub_question(self) -> None:
        sel = EvidenceSelector(max_per_sub_question=2)
        results = sel.select([
            _coverage("Q1", CoverageStatus.SUPPORTED, [_evidence() for _ in range(5)]),
            _coverage("Q2", CoverageStatus.SUPPORTED, [_evidence() for _ in range(5)]),
        ])
        assert len(results[0].evidence) == 2
        assert len(results[1].evidence) == 2


# ---------------------------------------------------------------------------
# deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_shared_chunk_appears_only_once_across_sub_questions(self) -> None:
        shared_id = uuid.uuid4()
        ev_shared_q1 = _evidence(chunk_id=shared_id)
        ev_shared_q2 = _evidence(chunk_id=shared_id)
        sel = EvidenceSelector(max_per_sub_question=5)

        results = sel.select([
            _coverage("Q1", CoverageStatus.SUPPORTED, [ev_shared_q1]),
            _coverage("Q2", CoverageStatus.SUPPORTED, [ev_shared_q2]),
        ])

        # Chunk appears in exactly one sub-question's evidence.
        q1_ids = {ev.chunk.id for ev in results[0].evidence}
        q2_ids = {ev.chunk.id for ev in results[1].evidence}
        assert (shared_id in q1_ids) != (shared_id in q2_ids)

    def test_supported_claims_shared_chunk_over_unsupported(self) -> None:
        shared_id = uuid.uuid4()
        sel = EvidenceSelector(max_per_sub_question=5)

        results = sel.select([
            _coverage("Q1", CoverageStatus.UNSUPPORTED, [_evidence(chunk_id=shared_id)]),
            _coverage("Q2", CoverageStatus.SUPPORTED, [_evidence(chunk_id=shared_id)]),
        ])

        q1_ids = {ev.chunk.id for ev in results[0].evidence}
        q2_ids = {ev.chunk.id for ev in results[1].evidence}
        assert shared_id not in q1_ids
        assert shared_id in q2_ids

    def test_supported_claims_shared_chunk_over_partially_supported(self) -> None:
        shared_id = uuid.uuid4()
        sel = EvidenceSelector(max_per_sub_question=5)

        results = sel.select([
            _coverage("Q1", CoverageStatus.PARTIALLY_SUPPORTED, [_evidence(chunk_id=shared_id)]),
            _coverage("Q2", CoverageStatus.SUPPORTED, [_evidence(chunk_id=shared_id)]),
        ])

        q1_ids = {ev.chunk.id for ev in results[0].evidence}
        q2_ids = {ev.chunk.id for ev in results[1].evidence}
        assert shared_id not in q1_ids
        assert shared_id in q2_ids

    def test_partially_supported_claims_over_conflicting(self) -> None:
        shared_id = uuid.uuid4()
        sel = EvidenceSelector(max_per_sub_question=5)

        results = sel.select([
            _coverage("Q1", CoverageStatus.CONFLICTING, [_evidence(chunk_id=shared_id)]),
            _coverage("Q2", CoverageStatus.PARTIALLY_SUPPORTED, [_evidence(chunk_id=shared_id)]),
        ])

        q1_ids = {ev.chunk.id for ev in results[0].evidence}
        q2_ids = {ev.chunk.id for ev in results[1].evidence}
        assert shared_id not in q1_ids
        assert shared_id in q2_ids

    def test_conflicting_claims_over_unsupported(self) -> None:
        shared_id = uuid.uuid4()
        sel = EvidenceSelector(max_per_sub_question=5)

        results = sel.select([
            _coverage("Q1", CoverageStatus.UNSUPPORTED, [_evidence(chunk_id=shared_id)]),
            _coverage("Q2", CoverageStatus.CONFLICTING, [_evidence(chunk_id=shared_id)]),
        ])

        q1_ids = {ev.chunk.id for ev in results[0].evidence}
        q2_ids = {ev.chunk.id for ev in results[1].evidence}
        assert shared_id not in q1_ids
        assert shared_id in q2_ids

    def test_non_shared_chunks_all_kept(self) -> None:
        ev1, ev2, ev3 = _evidence(), _evidence(), _evidence()
        sel = EvidenceSelector(max_per_sub_question=5)

        results = sel.select([
            _coverage("Q1", CoverageStatus.SUPPORTED, [ev1, ev2]),
            _coverage("Q2", CoverageStatus.SUPPORTED, [ev3]),
        ])

        q1_ids = {ev.chunk.id for ev in results[0].evidence}
        q2_ids = {ev.chunk.id for ev in results[1].evidence}
        assert ev1.chunk.id in q1_ids
        assert ev2.chunk.id in q1_ids
        assert ev3.chunk.id in q2_ids


# ---------------------------------------------------------------------------
# result structure and ordering
# ---------------------------------------------------------------------------


class TestResultStructure:
    def test_results_in_original_input_order(self) -> None:
        sel = EvidenceSelector()
        # UNSUPPORTED appears first in input even though SUPPORTED has higher priority.
        results = sel.select([
            _coverage("Q1", CoverageStatus.UNSUPPORTED),
            _coverage("Q2", CoverageStatus.SUPPORTED, [_evidence()]),
        ])
        assert results[0].sub_question.id == "Q1"
        assert results[1].sub_question.id == "Q2"

    def test_coverage_status_preserved(self) -> None:
        sel = EvidenceSelector()
        results = sel.select([
            _coverage("Q1", CoverageStatus.CONFLICTING, [_evidence()]),
        ])
        assert results[0].coverage is CoverageStatus.CONFLICTING

    def test_sub_question_carried_through(self) -> None:
        sq = _sq("Q7")
        cov = SubQuestionCoverage(sub_question=sq, evidence=[_evidence()], coverage=CoverageStatus.SUPPORTED)
        sel = EvidenceSelector()
        results = sel.select([cov])
        assert results[0].sub_question is sq

    def test_result_count_matches_input_count(self) -> None:
        sel = EvidenceSelector()
        coverages = [
            _coverage("Q1", CoverageStatus.SUPPORTED),
            _coverage("Q2", CoverageStatus.UNSUPPORTED),
            _coverage("Q3", CoverageStatus.PARTIALLY_SUPPORTED),
        ]
        results = sel.select(coverages)
        assert len(results) == 3

    def test_evidence_is_tuple(self) -> None:
        sel = EvidenceSelector()
        results = sel.select([_coverage("Q1", CoverageStatus.SUPPORTED, [_evidence()])])
        assert isinstance(results[0].evidence, tuple)
