"""Tests for MultiHopAnswerUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.application.commands.decompose import DecomposeQueryCommand
from app.application.commands.multi_hop_answer import MultiHopAnswerCommand, MultiHopAnswerUseCase
from app.application.queries.coverage_classifier import SubQuestionCoverage
from app.application.queries.evidence_selector import EvidenceSelector, SubQuestionEvidence
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer, MultiHopAnswer
from app.application.queries.iterative_retrieval import (
    IterativeRetrievalLoop,
    IterativeRetrievalResult,
)
from app.domain.enums import CoverageStatus
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sq(sq_id: str) -> SubQuestion:
    return SubQuestion(id=sq_id, text=f"Question {sq_id}?")


def _plan(*ids: str) -> DecompositionPlan:
    return DecompositionPlan.build("original query", [_sq(q) for q in ids])


def _coverage(sq_id: str) -> SubQuestionCoverage:
    return SubQuestionCoverage(
        sub_question=_sq(sq_id), evidence=[], coverage=CoverageStatus.SUPPORTED
    )


def _sub_evidence(sq_id: str) -> SubQuestionEvidence:
    return SubQuestionEvidence(
        sub_question=_sq(sq_id), evidence=(), coverage=CoverageStatus.SUPPORTED
    )


def _scope() -> MagicMock:
    return MagicMock(spec=ScopeContext)


def _make_use_case(
    *,
    plan: DecompositionPlan | None = None,
    coverages: list[SubQuestionCoverage] | None = None,
    selected: list[SubQuestionEvidence] | None = None,
    final_answer: str = "the final multi-hop answer",
) -> tuple[MultiHopAnswerUseCase, AsyncMock, AsyncMock, MagicMock, AsyncMock]:
    """Build a fully mocked MultiHopAnswerUseCase with controllable returns."""
    if plan is None:
        plan = _plan("Q1")
    if coverages is None:
        coverages = [_coverage("Q1")]
    if selected is None:
        selected = [_sub_evidence("Q1")]

    decompose = AsyncMock()
    decompose.execute = AsyncMock(return_value=plan)

    loop = AsyncMock(spec=IterativeRetrievalLoop)
    loop.run = AsyncMock(
        return_value=IterativeRetrievalResult(coverages=coverages, rounds_run=1)
    )

    selector = MagicMock(spec=EvidenceSelector)
    selector.select = MagicMock(return_value=selected)

    synthesizer = AsyncMock(spec=HierarchicalSynthesizer)
    synthesizer.synthesize = AsyncMock(
        return_value=MultiHopAnswer(answer=final_answer, sub_answers=())
    )

    uc = MultiHopAnswerUseCase(
        decompose=decompose,
        loop=loop,
        selector=selector,
        synthesizer=synthesizer,
    )
    return uc, decompose, loop, selector, synthesizer


# ---------------------------------------------------------------------------
# stage 1: decomposition
# ---------------------------------------------------------------------------


class TestDecomposition:
    async def test_decompose_called_with_query(self) -> None:
        uc, decompose, *_ = _make_use_case()
        cmd = MultiHopAnswerCommand(scope=_scope(), query="What links A and B?")

        await uc.execute(cmd)

        decompose.execute.assert_awaited_once()
        call_cmd: DecomposeQueryCommand = decompose.execute.call_args.args[0]
        assert call_cmd.query == "What links A and B?"

    async def test_decompose_called_with_scope(self) -> None:
        uc, decompose, *_ = _make_use_case()
        scope = _scope()
        cmd = MultiHopAnswerCommand(scope=scope, query="q")

        await uc.execute(cmd)

        call_cmd: DecomposeQueryCommand = decompose.execute.call_args.args[0]
        assert call_cmd.scope is scope


# ---------------------------------------------------------------------------
# stage 2: iterative retrieval loop
# ---------------------------------------------------------------------------


class TestIterativeLoop:
    async def test_loop_called_with_plan_from_decomposer(self) -> None:
        plan = _plan("Q1", "Q2")
        uc, _, loop, *_ = _make_use_case(plan=plan)
        await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        loop.run.assert_awaited_once()
        loop_plan = loop.run.call_args.args[0]
        assert loop_plan is plan

    async def test_loop_called_with_scope(self) -> None:
        uc, _, loop, *_ = _make_use_case()
        scope = _scope()
        await uc.execute(MultiHopAnswerCommand(scope=scope, query="q"))

        loop_scope = loop.run.call_args.args[1]
        assert loop_scope is scope

    async def test_loop_called_with_no_filters_when_command_has_empty_filters(self) -> None:
        uc, _, loop, *_ = _make_use_case()
        cmd = MultiHopAnswerCommand(scope=_scope(), query="q")

        await uc.execute(cmd)

        filters_kwarg = loop.run.call_args.kwargs.get("filters")
        assert filters_kwarg is None

    async def test_loop_called_with_filters_when_command_specifies_document_ids(self) -> None:
        import uuid
        doc_id = uuid.uuid4()
        uc, _, loop, *_ = _make_use_case()
        cmd = MultiHopAnswerCommand(
            scope=_scope(),
            query="q",
            filters=RetrievalFilters(document_ids=frozenset({doc_id})),
        )

        await uc.execute(cmd)

        filters_kwarg = loop.run.call_args.kwargs.get("filters")
        assert filters_kwarg is not None
        assert doc_id in filters_kwarg.document_ids


# ---------------------------------------------------------------------------
# stage 3: evidence selector
# ---------------------------------------------------------------------------


class TestEvidenceSelector:
    async def test_selector_called_with_loop_coverages(self) -> None:
        coverages = [_coverage("Q1"), _coverage("Q2")]
        uc, _, _, selector, _ = _make_use_case(coverages=coverages)
        await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        selector.select.assert_called_once_with(coverages)

    async def test_selector_receives_coverages_from_iterative_result(self) -> None:
        coverages = [_coverage("Q3")]
        uc, _, loop, selector, _ = _make_use_case(coverages=coverages)
        loop.run = AsyncMock(
            return_value=IterativeRetrievalResult(coverages=coverages, rounds_run=2)
        )
        await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        selector.select.assert_called_once_with(coverages)


# ---------------------------------------------------------------------------
# stage 4: hierarchical synthesis
# ---------------------------------------------------------------------------


class TestHierarchicalSynthesis:
    async def test_synthesizer_called_with_original_query(self) -> None:
        uc, *_, synthesizer = _make_use_case()
        await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="how does osmosis work?"))

        call_query = synthesizer.synthesize.call_args.args[0]
        assert call_query == "how does osmosis work?"

    async def test_synthesizer_called_with_selected_evidence(self) -> None:
        selected = [_sub_evidence("Q1"), _sub_evidence("Q2")]
        uc, _, _, _, synthesizer = _make_use_case(selected=selected)
        await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        call_selected = synthesizer.synthesize.call_args.args[1]
        assert call_selected == selected

    async def test_returns_multi_hop_answer_from_synthesizer(self) -> None:
        uc, *_ = _make_use_case(final_answer="synthesized answer text")
        result = await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        assert result.answer == "synthesized answer text"

    async def test_returns_multi_hop_answer_type(self) -> None:
        uc, *_ = _make_use_case()
        result = await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        assert isinstance(result, MultiHopAnswer)


# ---------------------------------------------------------------------------
# pipeline ordering — stages execute in the right sequence
# ---------------------------------------------------------------------------


class TestPipelineOrdering:
    async def test_all_four_stages_called(self) -> None:
        uc, decompose, loop, selector, synthesizer = _make_use_case()
        await uc.execute(MultiHopAnswerCommand(scope=_scope(), query="q"))

        decompose.execute.assert_awaited_once()
        loop.run.assert_awaited_once()
        selector.select.assert_called_once()
        synthesizer.synthesize.assert_awaited_once()
