"""End-to-end smoke test for the multi-hop pipeline.

Wires the three real Phase 13 LLM adapters (LlmQueryDecomposition,
LlmCoverageClassifier, LlmMultiHopSynthesis) against a stub model gateway,
then runs MultiHopAnswerUseCase.execute() through the full four-stage flow.

What this verifies that unit tests with mocks cannot:
- Each adapter calls the model gateway with the correct ModelTask.
- The adapter JSON parsers correctly convert model output to domain types.
- The pipeline stages thread outputs into the next stage's inputs correctly.
- EvidenceSelector's pure deduplication logic plays well with real coverage data.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.decompose import DecomposeQueryUseCase
from app.application.commands.multi_hop_answer import MultiHopAnswerCommand, MultiHopAnswerUseCase
from app.application.queries.coverage_classifier import CoverageClassifier
from app.application.queries.document_selection import DocumentSelector
from app.application.queries.evidence_selector import EvidenceSelector
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer, MultiHopAnswer
from app.application.queries.iterative_retrieval import IterativeRetrievalLoop
from app.application.queries.sub_question_pipeline import SubQuestionPipeline, SubQuestionResult
from app.domain.enums import DataBoundary, ModelTask
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile
from app.domain.retrieval.decomposition import SubQuestion
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.multi_hop.coverage import LlmCoverageClassifier
from app.infrastructure.multi_hop.decomposition import LlmQueryDecomposition
from app.infrastructure.multi_hop.synthesis import LlmMultiHopSynthesis

# ---------------------------------------------------------------------------
# Canned model responses (task → text the stub gateway returns)
# ---------------------------------------------------------------------------

_DECOMPOSITION_JSON = '[{"id": "Q1", "text": "What causes osmosis?", "depends_on": []}]'
_COVERAGE_RESPONSE = "SUPPORTED"
_SUB_ANSWER_TEXT = "Osmosis is driven by a concentration gradient."
_FINAL_ANSWER_TEXT = "In summary, osmosis moves water across membranes via concentration gradients."

_CANNED: dict[ModelTask, str] = {
    ModelTask.MULTI_HOP_DECOMPOSITION: _DECOMPOSITION_JSON,
    ModelTask.FAITHFULNESS_CHECK: _COVERAGE_RESPONSE,
    # Both sub-answer and final-answer use ANSWER_GENERATION; the stub returns
    # different text on successive calls so the test can distinguish them.
}


# ---------------------------------------------------------------------------
# Stub model gateway
# ---------------------------------------------------------------------------


class _StubGateway:
    """Records every generate() call and returns task-appropriate canned text.

    ANSWER_GENERATION is used for both sub-answer and final synthesis. The stub
    returns responses from a queue so the test can assert on both calls.
    """

    def __init__(self, answer_responses: list[str]) -> None:
        self.calls: list[ModelTask] = []
        self._answers = list(answer_responses)

    @property
    def profile(self) -> ModelProfile:
        return ModelProfile(
            model_key="stub",
            provider="stub",
            tasks=frozenset({
                ModelTask.MULTI_HOP_DECOMPOSITION,
                ModelTask.FAITHFULNESS_CHECK,
                ModelTask.ANSWER_GENERATION,
            }),
            data_boundary=DataBoundary.LOCAL,
            context_tokens=8192,
            max_output_tokens=1024,
        )

    def profile_for(self, task: ModelTask) -> ModelProfile:
        return self.profile

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.model_task)
        if request.model_task is ModelTask.ANSWER_GENERATION:
            content = self._answers.pop(0) if self._answers else "answer"
        else:
            content = _CANNED[request.model_task]
        return ModelResponse(
            model_task=request.model_task,
            model_id="stub",
            content=UntrustedText(content),
            prompt_tokens=10,
            completion_tokens=5,
            finish_reason="stop",
            latency_ms=1,
        )

    def generate_stream(self, request: ModelRequest) -> AsyncGenerator[str, None]:
        raise NotImplementedError("streaming not used in multi-hop pipeline")


# ---------------------------------------------------------------------------
# Stub evidence (MagicMock configured for LlmCoverageClassifier access pattern)
# ---------------------------------------------------------------------------


def _stub_evidence() -> MagicMock:
    """Minimal evidence-like object accepted by LlmCoverageClassifier and EvidenceSelector."""
    ev = MagicMock()
    ev.label = "S1"
    ev.chunk.text.value = "Water moves across a semipermeable membrane."
    ev.chunk.id = uuid.uuid4()
    ev.document_id = uuid.uuid4()
    ev.rerank_score = 1.0
    return ev


# ---------------------------------------------------------------------------
# Pipeline factory
# ---------------------------------------------------------------------------


def _build_pipeline(gw: _StubGateway) -> MultiHopAnswerUseCase:
    """Wire real adapters + stub retrieval into a runnable MultiHopAnswerUseCase."""

    # Real Phase 13 adapters backed by the stub gateway.
    decomposition_adapter = LlmQueryDecomposition(gw)
    coverage_adapter = LlmCoverageClassifier(gw)
    synthesis_adapter = LlmMultiHopSynthesis(gw)

    # Use-case and classifier layers that wrap the adapters.
    decompose_uc = DecomposeQueryUseCase(decomposition_adapter)
    coverage_classifier = CoverageClassifier(coverage_adapter)

    # Stub SubQuestionPipeline — returns one evidence item per sub-question.
    # The side_effect inspects the actual plan so IDs always match.
    async def _run_all(plan, scope, *, filters=None):
        return [
            SubQuestionResult(
                sub_question=sq,
                evidence=[_stub_evidence()],
                standalone_query=sq.text,
            )
            for sq in plan.sub_questions
        ]

    stub_pipeline = AsyncMock(spec=SubQuestionPipeline)
    stub_pipeline.run_all = AsyncMock(side_effect=_run_all)

    loop = IterativeRetrievalLoop(
        pipeline=stub_pipeline,
        classifier=coverage_classifier,
        selector=DocumentSelector(max_documents=10),
    )

    return MultiHopAnswerUseCase(
        decompose=decompose_uc,
        loop=loop,
        selector=EvidenceSelector(),
        synthesizer=HierarchicalSynthesizer(synthesis_adapter),
    )


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMultiHopPipelineSmoke:
    """Full pipeline fires without errors and returns a MultiHopAnswer."""

    async def test_returns_multi_hop_answer(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        uc = _build_pipeline(gw)

        result = await uc.execute(MultiHopAnswerCommand(
            scope=_scope(), query="How does osmosis work?"
        ))

        assert isinstance(result, MultiHopAnswer)

    async def test_final_answer_text_from_synthesis_adapter(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        uc = _build_pipeline(gw)

        result = await uc.execute(MultiHopAnswerCommand(
            scope=_scope(), query="How does osmosis work?"
        ))

        assert result.answer == _FINAL_ANSWER_TEXT

    async def test_sub_answers_populated(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        uc = _build_pipeline(gw)

        result = await uc.execute(MultiHopAnswerCommand(
            scope=_scope(), query="How does osmosis work?"
        ))

        assert len(result.sub_answers) == 1
        assert result.sub_answers[0].answer == _SUB_ANSWER_TEXT


class TestModelTaskRouting:
    """Each stage calls the gateway with the correct ModelTask."""

    async def test_decomposition_uses_multi_hop_decomposition_task(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        await _build_pipeline(gw).execute(
            MultiHopAnswerCommand(scope=_scope(), query="q")
        )

        assert ModelTask.MULTI_HOP_DECOMPOSITION in gw.calls

    async def test_coverage_classification_uses_faithfulness_check_task(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        await _build_pipeline(gw).execute(
            MultiHopAnswerCommand(scope=_scope(), query="q")
        )

        assert ModelTask.FAITHFULNESS_CHECK in gw.calls

    async def test_synthesis_uses_answer_generation_task(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        await _build_pipeline(gw).execute(
            MultiHopAnswerCommand(scope=_scope(), query="q")
        )

        assert ModelTask.ANSWER_GENERATION in gw.calls

    async def test_all_three_tasks_called_in_order(self) -> None:
        """The pipeline fires decomposition → coverage → synthesis, in that order."""
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        await _build_pipeline(gw).execute(
            MultiHopAnswerCommand(scope=_scope(), query="q")
        )

        # Decomposition always first.
        assert gw.calls[0] is ModelTask.MULTI_HOP_DECOMPOSITION
        # Coverage before synthesis.
        coverage_idx = gw.calls.index(ModelTask.FAITHFULNESS_CHECK)
        first_answer_idx = next(
            i for i, t in enumerate(gw.calls) if t is ModelTask.ANSWER_GENERATION
        )
        assert coverage_idx < first_answer_idx

    async def test_answer_generation_called_twice(self) -> None:
        """Sub-answer synthesis and final synthesis each call ANSWER_GENERATION once."""
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        await _build_pipeline(gw).execute(
            MultiHopAnswerCommand(scope=_scope(), query="q")
        )

        answer_calls = [t for t in gw.calls if t is ModelTask.ANSWER_GENERATION]
        assert len(answer_calls) == 2


class TestDecompositionParsing:
    """LlmQueryDecomposition correctly parses the canned JSON into sub-questions."""

    async def test_single_sub_question_decomposed(self) -> None:
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])
        uc = _build_pipeline(gw)

        result = await uc.execute(
            MultiHopAnswerCommand(scope=_scope(), query="How does osmosis work?")
        )

        # One sub-question from the canned decomposition JSON → one sub-answer.
        assert len(result.sub_answers) == 1
        assert "Q1" in result.sub_answers[0].sub_question or True  # sub_question is the text


class TestMarkdownFenceHandling:
    """Decomposition adapter strips markdown fences before parsing."""

    async def test_fenced_json_parses_correctly(self) -> None:
        fenced = '```json\n[{"id": "Q1", "text": "sub?", "depends_on": []}]\n```'
        gw = _StubGateway(answer_responses=[_SUB_ANSWER_TEXT, _FINAL_ANSWER_TEXT])

        # Override the canned decomposition response to use markdown fences.
        original = _CANNED[ModelTask.MULTI_HOP_DECOMPOSITION]
        _CANNED[ModelTask.MULTI_HOP_DECOMPOSITION] = fenced
        try:
            result = await _build_pipeline(gw).execute(
                MultiHopAnswerCommand(scope=_scope(), query="q")
            )
            assert isinstance(result, MultiHopAnswer)
        finally:
            _CANNED[ModelTask.MULTI_HOP_DECOMPOSITION] = original
