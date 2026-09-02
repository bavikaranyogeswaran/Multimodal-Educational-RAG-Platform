"""Tests for IterativeRetrievalLoop."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.queries.coverage_classifier import SubQuestionCoverage
from app.application.queries.document_selection import DocumentSelection, DocumentSelector
from app.application.queries.iterative_retrieval import IterativeRetrievalLoop
from app.application.queries.sub_question_pipeline import SubQuestionResult
from app.domain.enums import CoverageStatus
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.retrieval.entities import RetrievalFilters

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sq(sq_id: str) -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _plan(*ids: str) -> DecompositionPlan:
    return DecompositionPlan.build("original query", [_sq(q) for q in ids])


def _result(sq_id: str) -> SubQuestionResult:
    return SubQuestionResult(
        sub_question=_sq(sq_id),
        evidence=[],
        standalone_query=f"standalone {sq_id}",
    )


def _coverage(sq_id: str, status: CoverageStatus) -> SubQuestionCoverage:
    return SubQuestionCoverage(sub_question=_sq(sq_id), evidence=[], coverage=status)


def _make_pipeline(*rounds: list[SubQuestionResult]) -> AsyncMock:
    mock = AsyncMock()
    mock.run_all = AsyncMock(side_effect=list(rounds))
    return mock


def _make_classifier(*rounds: list[SubQuestionCoverage]) -> AsyncMock:
    mock = AsyncMock()
    mock.classify_all = AsyncMock(side_effect=list(rounds))
    return mock


def _make_selector(selected_ids: frozenset = frozenset()) -> MagicMock:
    sel = MagicMock(spec=DocumentSelector)
    sel.select.return_value = DocumentSelection(selected_ids=selected_ids, scores=())
    return sel


def _scope() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


class TestValidation:
    async def test_max_rounds_zero_raises(self) -> None:
        loop = IterativeRetrievalLoop(
            pipeline=_make_pipeline([]),
            classifier=_make_classifier([]),
            selector=_make_selector(),
        )
        with pytest.raises(ValueError, match="max_rounds"):
            await loop.run(_plan("Q1"), _scope(), max_rounds=0)

    async def test_max_rounds_negative_raises(self) -> None:
        loop = IterativeRetrievalLoop(
            pipeline=_make_pipeline([]),
            classifier=_make_classifier([]),
            selector=_make_selector(),
        )
        with pytest.raises(ValueError, match="max_rounds"):
            await loop.run(_plan("Q1"), _scope(), max_rounds=-1)


# ---------------------------------------------------------------------------
# single round — no retry needed
# ---------------------------------------------------------------------------


class TestSingleRound:
    async def test_all_supported_stops_after_round_1(self) -> None:
        pipeline = _make_pipeline([_result("Q1"), _result("Q2")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.SUPPORTED), _coverage("Q2", CoverageStatus.SUPPORTED)]
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1", "Q2"), _scope())

        assert result.rounds_run == 1
        pipeline.run_all.assert_awaited_once()
        classifier.classify_all.assert_awaited_once()

    async def test_max_rounds_one_never_retries_even_when_unsupported(self) -> None:
        pipeline = _make_pipeline([_result("Q1")])
        classifier = _make_classifier([_coverage("Q1", CoverageStatus.UNSUPPORTED)])
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope(), max_rounds=1)

        assert result.rounds_run == 1
        pipeline.run_all.assert_awaited_once()

    async def test_conflicting_does_not_trigger_retry(self) -> None:
        pipeline = _make_pipeline([_result("Q1")])
        classifier = _make_classifier([_coverage("Q1", CoverageStatus.CONFLICTING)])
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope())

        assert result.rounds_run == 1
        pipeline.run_all.assert_awaited_once()


# ---------------------------------------------------------------------------
# second round triggered
# ---------------------------------------------------------------------------


class TestSecondRound:
    async def test_unsupported_triggers_second_round(self) -> None:
        pipeline = _make_pipeline([_result("Q1")], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q1", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope())

        assert result.rounds_run == 2
        assert pipeline.run_all.await_count == 2
        assert classifier.classify_all.await_count == 2

    async def test_partially_supported_triggers_retry(self) -> None:
        pipeline = _make_pipeline([_result("Q1")], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.PARTIALLY_SUPPORTED)],
            [_coverage("Q1", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope())

        assert result.rounds_run == 2

    async def test_only_pending_sub_questions_in_retry_plan(self) -> None:
        pipeline = _make_pipeline(
            [_result("Q1"), _result("Q2")],
            [_result("Q2")],
        )
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.SUPPORTED), _coverage("Q2", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q2", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        await loop.run(_plan("Q1", "Q2"), _scope())

        retry_plan: DecompositionPlan = pipeline.run_all.call_args_list[1].args[0]
        sq_ids = [sq.id for sq in retry_plan.sub_questions]
        assert sq_ids == ["Q2"]
        assert "Q1" not in sq_ids

    async def test_retry_plan_has_no_cross_dependencies(self) -> None:
        # Q2 depends on Q1 in the original plan, but Q1 is satisfied after round 1.
        q1 = SubQuestion(id="Q1", text="Question Q1?")
        q2 = SubQuestion(id="Q2", text="Question Q2?", depends_on=frozenset({"Q1"}))
        original_plan = DecompositionPlan.build("query", [q1, q2])

        pipeline = _make_pipeline(
            [_result("Q1"), _result("Q2")],
            [_result("Q2")],
        )
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.SUPPORTED), _coverage("Q2", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q2", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        await loop.run(original_plan, _scope())

        retry_plan: DecompositionPlan = pipeline.run_all.call_args_list[1].args[0]
        retry_q2 = next(sq for sq in retry_plan.sub_questions if sq.id == "Q2")
        assert retry_q2.depends_on == frozenset()

    async def test_retry_document_filter_comes_from_selector(self) -> None:
        doc_id = uuid.uuid4()
        pipeline = _make_pipeline([_result("Q1")], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q1", CoverageStatus.SUPPORTED)],
        )
        selector = _make_selector(selected_ids=frozenset({doc_id}))
        loop = IterativeRetrievalLoop(pipeline, classifier, selector)

        await loop.run(_plan("Q1"), _scope())

        retry_filters: RetrievalFilters = pipeline.run_all.call_args_list[1].kwargs["filters"]
        assert doc_id in retry_filters.document_ids

    async def test_selector_receives_round1_results(self) -> None:
        r1 = _result("Q1")
        pipeline = _make_pipeline([r1], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q1", CoverageStatus.SUPPORTED)],
        )
        selector = _make_selector()
        loop = IterativeRetrievalLoop(pipeline, classifier, selector)

        await loop.run(_plan("Q1"), _scope())

        selector.select.assert_called_once()
        select_arg = selector.select.call_args.args[0]
        assert r1 in select_arg


# ---------------------------------------------------------------------------
# max rounds and stopping
# ---------------------------------------------------------------------------


class TestMaxRounds:
    async def test_stops_at_max_rounds_even_if_still_pending(self) -> None:
        pipeline = _make_pipeline([_result("Q1")], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope(), max_rounds=2)

        assert result.rounds_run == 2
        assert pipeline.run_all.await_count == 2

    async def test_stops_early_when_all_covered_before_max(self) -> None:
        pipeline = _make_pipeline([_result("Q1")], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q1", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope(), max_rounds=5)

        assert result.rounds_run == 2
        assert pipeline.run_all.await_count == 2


# ---------------------------------------------------------------------------
# result ordering and final coverage
# ---------------------------------------------------------------------------


class TestResults:
    async def test_coverages_in_original_plan_order(self) -> None:
        pipeline = _make_pipeline([_result("Q2"), _result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q2", CoverageStatus.SUPPORTED), _coverage("Q1", CoverageStatus.SUPPORTED)]
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q2", "Q1"), _scope())

        ids = [c.sub_question.id for c in result.coverages]
        assert ids == ["Q2", "Q1"]

    async def test_latest_coverage_replaces_earlier_for_retried_sub_question(self) -> None:
        pipeline = _make_pipeline([_result("Q1")], [_result("Q1")])
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q1", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope())

        assert result.coverages[0].coverage is CoverageStatus.SUPPORTED

    async def test_non_retried_sub_question_keeps_round1_coverage(self) -> None:
        pipeline = _make_pipeline(
            [_result("Q1"), _result("Q2")],
            [_result("Q2")],
        )
        classifier = _make_classifier(
            [_coverage("Q1", CoverageStatus.SUPPORTED), _coverage("Q2", CoverageStatus.UNSUPPORTED)],
            [_coverage("Q2", CoverageStatus.SUPPORTED)],
        )
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1", "Q2"), _scope())

        q1_cov = next(c for c in result.coverages if c.sub_question.id == "Q1")
        assert q1_cov.coverage is CoverageStatus.SUPPORTED

    async def test_rounds_run_one_when_all_satisfied_immediately(self) -> None:
        pipeline = _make_pipeline([_result("Q1")])
        classifier = _make_classifier([_coverage("Q1", CoverageStatus.SUPPORTED)])
        loop = IterativeRetrievalLoop(pipeline, classifier, _make_selector())

        result = await loop.run(_plan("Q1"), _scope())

        assert result.rounds_run == 1
