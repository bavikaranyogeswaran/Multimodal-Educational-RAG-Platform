"""Tests for CoverageClassifier."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.application.queries.coverage_classifier import (
    CoverageClassifier,
    SubQuestionCoverage,
)
from app.application.queries.sub_question_pipeline import SubQuestionResult
from app.domain.enums import CoverageStatus
from app.domain.retrieval.decomposition import SubQuestion

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sq(sq_id: str = "Q1") -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _evidence() -> MagicMock:
    ev = MagicMock()
    ev.document_id = uuid.uuid4()
    ev.rerank_score = 1.0
    return ev


def _result(sq_id: str, *, has_evidence: bool = True) -> SubQuestionResult:
    return SubQuestionResult(
        sub_question=_sq(sq_id),
        evidence=[_evidence()] if has_evidence else [],
        standalone_query=f"standalone {sq_id}",
    )


def _port(*, status: CoverageStatus = CoverageStatus.SUPPORTED) -> AsyncMock:
    port = AsyncMock()
    port.classify = AsyncMock(return_value=status)
    return port


# ---------------------------------------------------------------------------
# fast path — empty evidence
# ---------------------------------------------------------------------------


class TestFastPath:
    async def test_empty_evidence_returns_unsupported_without_port_call(self) -> None:
        port = _port()
        classifier = CoverageClassifier(port)

        coverages = await classifier.classify_all([_result("Q1", has_evidence=False)])

        assert coverages[0].coverage is CoverageStatus.UNSUPPORTED
        port.classify.assert_not_awaited()

    async def test_empty_results_list_returns_empty(self) -> None:
        port = _port()
        classifier = CoverageClassifier(port)

        coverages = await classifier.classify_all([])

        assert coverages == []
        port.classify.assert_not_awaited()

    async def test_mixed_empty_and_non_empty_only_calls_port_for_non_empty(self) -> None:
        port = _port(status=CoverageStatus.SUPPORTED)
        classifier = CoverageClassifier(port)

        coverages = await classifier.classify_all([
            _result("Q1", has_evidence=False),
            _result("Q2", has_evidence=True),
        ])

        port.classify.assert_awaited_once()
        assert coverages[0].coverage is CoverageStatus.UNSUPPORTED
        assert coverages[1].coverage is CoverageStatus.SUPPORTED


# ---------------------------------------------------------------------------
# all four coverage statuses
# ---------------------------------------------------------------------------


class TestCoverageStatuses:
    async def test_supported(self) -> None:
        port = _port(status=CoverageStatus.SUPPORTED)
        coverages = await CoverageClassifier(port).classify_all([_result("Q1")])
        assert coverages[0].coverage is CoverageStatus.SUPPORTED

    async def test_partially_supported(self) -> None:
        port = _port(status=CoverageStatus.PARTIALLY_SUPPORTED)
        coverages = await CoverageClassifier(port).classify_all([_result("Q1")])
        assert coverages[0].coverage is CoverageStatus.PARTIALLY_SUPPORTED

    async def test_unsupported_via_port(self) -> None:
        port = _port(status=CoverageStatus.UNSUPPORTED)
        coverages = await CoverageClassifier(port).classify_all([_result("Q1")])
        assert coverages[0].coverage is CoverageStatus.UNSUPPORTED

    async def test_conflicting(self) -> None:
        port = _port(status=CoverageStatus.CONFLICTING)
        coverages = await CoverageClassifier(port).classify_all([_result("Q1")])
        assert coverages[0].coverage is CoverageStatus.CONFLICTING


# ---------------------------------------------------------------------------
# port receives correct arguments
# ---------------------------------------------------------------------------


class TestPortArguments:
    async def test_port_receives_sub_question_text(self) -> None:
        port = _port()
        sq = SubQuestion(id="Q1", text="What is osmosis?")
        result = SubQuestionResult(
            sub_question=sq, evidence=[_evidence()], standalone_query="osmosis"
        )

        await CoverageClassifier(port).classify_all([result])

        args = port.classify.call_args[0]
        assert args[0] == "What is osmosis?"

    async def test_port_receives_evidence_list(self) -> None:
        port = _port()
        ev = _evidence()
        result = SubQuestionResult(
            sub_question=_sq(), evidence=[ev], standalone_query="q"
        )

        await CoverageClassifier(port).classify_all([result])

        args = port.classify.call_args[0]
        assert ev in args[1]


# ---------------------------------------------------------------------------
# ordering and concurrency
# ---------------------------------------------------------------------------


class TestOrderingAndConcurrency:
    async def test_results_in_same_order_as_input(self) -> None:
        statuses = [
            CoverageStatus.SUPPORTED,
            CoverageStatus.PARTIALLY_SUPPORTED,
            CoverageStatus.CONFLICTING,
        ]
        port = AsyncMock()
        port.classify = AsyncMock(side_effect=statuses)
        classifier = CoverageClassifier(port)

        coverages = await classifier.classify_all([
            _result("Q1"),
            _result("Q2"),
            _result("Q3"),
        ])

        assert [c.coverage for c in coverages] == statuses

    async def test_all_sub_questions_classified(self) -> None:
        port = _port(status=CoverageStatus.SUPPORTED)
        classifier = CoverageClassifier(port)

        coverages = await classifier.classify_all([
            _result("Q1"),
            _result("Q2"),
            _result("Q3"),
        ])

        assert port.classify.await_count == 3
        assert len(coverages) == 3

    async def test_sub_question_carried_through(self) -> None:
        port = _port()
        sq = SubQuestion(id="Q7", text="Specific question?")
        result = SubQuestionResult(
            sub_question=sq, evidence=[_evidence()], standalone_query="q"
        )

        coverages = await CoverageClassifier(port).classify_all([result])

        assert coverages[0].sub_question is sq

    async def test_evidence_carried_through(self) -> None:
        port = _port()
        ev = _evidence()
        result = SubQuestionResult(
            sub_question=_sq(), evidence=[ev], standalone_query="q"
        )

        coverages = await CoverageClassifier(port).classify_all([result])

        assert ev in coverages[0].evidence


# ---------------------------------------------------------------------------
# SubQuestionCoverage convenience properties
# ---------------------------------------------------------------------------


class TestSubQuestionCoverageProperties:
    def test_needs_another_round_partially_supported(self) -> None:
        cov = SubQuestionCoverage(
            sub_question=_sq(), evidence=[], coverage=CoverageStatus.PARTIALLY_SUPPORTED
        )
        assert cov.needs_another_round is True

    def test_needs_another_round_unsupported(self) -> None:
        cov = SubQuestionCoverage(
            sub_question=_sq(), evidence=[], coverage=CoverageStatus.UNSUPPORTED
        )
        assert cov.needs_another_round is True

    def test_needs_another_round_supported(self) -> None:
        cov = SubQuestionCoverage(
            sub_question=_sq(), evidence=[], coverage=CoverageStatus.SUPPORTED
        )
        assert cov.needs_another_round is False

    def test_needs_another_round_conflicting(self) -> None:
        cov = SubQuestionCoverage(
            sub_question=_sq(), evidence=[], coverage=CoverageStatus.CONFLICTING
        )
        assert cov.needs_another_round is False

    def test_is_conflicting_true(self) -> None:
        cov = SubQuestionCoverage(
            sub_question=_sq(), evidence=[], coverage=CoverageStatus.CONFLICTING
        )
        assert cov.is_conflicting is True

    def test_is_conflicting_false_for_supported(self) -> None:
        cov = SubQuestionCoverage(
            sub_question=_sq(), evidence=[], coverage=CoverageStatus.SUPPORTED
        )
        assert cov.is_conflicting is False
