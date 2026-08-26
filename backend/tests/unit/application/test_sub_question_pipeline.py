"""Tests for SubQuestionPipeline."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.application.queries.retrieve_evidence import RetrievalResult
from app.application.queries.sub_question_pipeline import (
    SubQuestionPipeline,
    SubQuestionResult,
    _topological_levels,
)
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _retrieval_result(*, query: str = "q", evidence: Sequence = ()) -> RetrievalResult:
    return RetrievalResult(evidence=evidence, standalone_query=query, was_rewritten=False)


def _orchestrator(*, results: list[RetrievalResult] | None = None) -> AsyncMock:
    """Return a mock orchestrator that cycles through the supplied RetrievalResults."""
    orch = AsyncMock()
    if results is None:
        results = []
    orch.execute = AsyncMock(side_effect=results if results else [_retrieval_result()])
    return orch


def _plan(*sub_questions: SubQuestion) -> DecompositionPlan:
    return DecompositionPlan.build("parent query", list(sub_questions))


# ---------------------------------------------------------------------------
# _topological_levels
# ---------------------------------------------------------------------------


class TestTopologicalLevels:
    def test_single_independent(self) -> None:
        sq = SubQuestion(id="Q1", text="First?")
        plan = _plan(sq)
        levels = _topological_levels(plan)
        assert len(levels) == 1
        assert levels[0] == [sq]

    def test_two_independent_in_same_level(self) -> None:
        sq1 = SubQuestion(id="Q1", text="First?")
        sq2 = SubQuestion(id="Q2", text="Second?")
        plan = _plan(sq1, sq2)
        levels = _topological_levels(plan)
        assert len(levels) == 1
        assert set(sq.id for sq in levels[0]) == {"Q1", "Q2"}

    def test_chain_yields_separate_levels(self) -> None:
        sq1 = SubQuestion(id="Q1", text="First?")
        sq2 = SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"}))
        sq3 = SubQuestion(id="Q3", text="Third?", depends_on=frozenset({"Q2"}))
        plan = _plan(sq1, sq2, sq3)
        levels = _topological_levels(plan)
        assert len(levels) == 3
        assert [sq.id for sq in levels[0]] == ["Q1"]
        assert [sq.id for sq in levels[1]] == ["Q2"]
        assert [sq.id for sq in levels[2]] == ["Q3"]

    def test_diamond_q1_q2_independent_q3_depends_on_both(self) -> None:
        # Q1 and Q2 are independent (level 0); Q3 depends on both (level 1)
        sq1 = SubQuestion(id="Q1", text="First?")
        sq2 = SubQuestion(id="Q2", text="Second?")
        sq3 = SubQuestion(id="Q3", text="Third?", depends_on=frozenset({"Q1", "Q2"}))
        plan = _plan(sq1, sq2, sq3)
        levels = _topological_levels(plan)
        assert len(levels) == 2
        assert set(sq.id for sq in levels[0]) == {"Q1", "Q2"}
        assert [sq.id for sq in levels[1]] == ["Q3"]


# ---------------------------------------------------------------------------
# SubQuestionPipeline.run_all
# ---------------------------------------------------------------------------


class TestSubQuestionPipelineRunAll:
    async def test_single_sub_question_calls_orchestrator_once(self) -> None:
        sq = SubQuestion(id="Q1", text="What is entropy?")
        plan = _plan(sq)
        orch = _orchestrator(results=[_retrieval_result(query="What is entropy?")])
        pipeline = SubQuestionPipeline(orch)

        results = await pipeline.run_all(plan, _scope())

        assert len(results) == 1
        orch.execute.assert_awaited_once()

    async def test_result_carries_sub_question(self) -> None:
        sq = SubQuestion(id="Q1", text="What is entropy?")
        plan = _plan(sq)
        orch = _orchestrator(results=[_retrieval_result(query="entropy standalone")])
        pipeline = SubQuestionPipeline(orch)

        results = await pipeline.run_all(plan, _scope())

        assert results[0].sub_question.id == "Q1"
        assert results[0].standalone_query == "entropy standalone"

    async def test_two_independent_sub_questions_both_retrieved(self) -> None:
        sq1 = SubQuestion(id="Q1", text="First?")
        sq2 = SubQuestion(id="Q2", text="Second?")
        plan = _plan(sq1, sq2)
        orch = _orchestrator(
            results=[_retrieval_result(query="First?"), _retrieval_result(query="Second?")]
        )
        pipeline = SubQuestionPipeline(orch)

        results = await pipeline.run_all(plan, _scope())

        assert len(results) == 2
        assert orch.execute.await_count == 2

    async def test_results_in_topological_order(self) -> None:
        sq1 = SubQuestion(id="Q1", text="First?")
        sq2 = SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"}))
        plan = _plan(sq1, sq2)
        orch = _orchestrator(
            results=[_retrieval_result(query="First?"), _retrieval_result(query="Second?")]
        )
        pipeline = SubQuestionPipeline(orch)

        results = await pipeline.run_all(plan, _scope())

        assert results[0].sub_question.id == "Q1"
        assert results[1].sub_question.id == "Q2"

    async def test_dependent_sub_questions_run_in_correct_level_order(self) -> None:
        """Verify Q1 retrieval completes before Q2 is dispatched."""
        call_order: list[str] = []

        async def _execute(query_obj):  # type: ignore[no-untyped-def]
            call_order.append(query_obj.query)
            await asyncio.sleep(0)  # yield so concurrent tasks could interleave
            return _retrieval_result(query=query_obj.query)

        sq1 = SubQuestion(id="Q1", text="Q1 text")
        sq2 = SubQuestion(id="Q2", text="Q2 text", depends_on=frozenset({"Q1"}))
        plan = _plan(sq1, sq2)

        orch = AsyncMock()
        orch.execute = _execute
        pipeline = SubQuestionPipeline(orch)

        results = await pipeline.run_all(plan, _scope())

        assert call_order[0] == "Q1 text"
        assert call_order[1] == "Q2 text"
        assert results[0].sub_question.id == "Q1"
        assert results[1].sub_question.id == "Q2"

    async def test_custom_filters_forwarded_to_orchestrator(self) -> None:
        sq = SubQuestion(id="Q1", text="Question?")
        plan = _plan(sq)
        orch = _orchestrator(results=[_retrieval_result()])
        pipeline = SubQuestionPipeline(orch)
        doc_id = uuid.uuid4()
        filters = RetrievalFilters(document_ids=frozenset({doc_id}))

        await pipeline.run_all(plan, _scope(), filters=filters)

        called_query = orch.execute.call_args[0][0]
        assert called_query.filters == filters

    async def test_scope_forwarded_to_orchestrator(self) -> None:
        sq = SubQuestion(id="Q1", text="Question?")
        plan = _plan(sq)
        orch = _orchestrator(results=[_retrieval_result()])
        pipeline = SubQuestionPipeline(orch)
        scope = _scope()

        await pipeline.run_all(plan, scope)

        called_query = orch.execute.call_args[0][0]
        assert called_query.scope == scope

    async def test_three_sub_questions_in_chain(self) -> None:
        sq1 = SubQuestion(id="Q1", text="First?")
        sq2 = SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"}))
        sq3 = SubQuestion(id="Q3", text="Third?", depends_on=frozenset({"Q2"}))
        plan = _plan(sq1, sq2, sq3)
        orch = _orchestrator(
            results=[
                _retrieval_result(query="First?"),
                _retrieval_result(query="Second?"),
                _retrieval_result(query="Third?"),
            ]
        )
        pipeline = SubQuestionPipeline(orch)

        results = await pipeline.run_all(plan, _scope())

        assert [r.sub_question.id for r in results] == ["Q1", "Q2", "Q3"]
        assert orch.execute.await_count == 3

    async def test_default_filters_when_none_supplied(self) -> None:
        sq = SubQuestion(id="Q1", text="Q?")
        plan = _plan(sq)
        orch = _orchestrator(results=[_retrieval_result()])
        pipeline = SubQuestionPipeline(orch)

        await pipeline.run_all(plan, _scope())

        called_query = orch.execute.call_args[0][0]
        assert called_query.filters == RetrievalFilters()
