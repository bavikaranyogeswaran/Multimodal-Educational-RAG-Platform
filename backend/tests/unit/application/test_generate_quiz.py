"""Unit tests for GenerateQuizUseCase.

Verifies orchestration: evidence conversion, prompt construction, gateway call,
and the no-material fallback. No LLM or database involved.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.application.commands.generate_quiz import (
    GenerateQuizCommand,
    GenerateQuizUseCase,
    QuizResult,
    _NO_MATERIAL_MESSAGE,
)
from app.domain.enums import ModelTask
from app.domain.models.context_builder import ContextBuilder, ContextInputs
from app.domain.models.entities import LabeledPassage
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _mock_evidence(label: str = "S1", text: str = "passage text") -> MagicMock:
    ev = MagicMock()
    ev.label.bracketed = f"[{label}]"
    ev.chunk.text = UntrustedText(text)
    return ev


def _mock_gateway(response_text: str = "1. Question?") -> AsyncMock:
    gw = AsyncMock()
    gw.generate = AsyncMock()
    gw.generate.return_value.content.value = response_text
    return gw


def _mock_context_builder() -> MagicMock:
    cb = MagicMock(spec=ContextBuilder)
    cb.build = MagicMock(return_value=MagicMock())
    return cb


def _make_use_case(
    *,
    response_text: str = "1. What is entropy?\n   Answer: A measure of disorder.",
) -> tuple[GenerateQuizUseCase, AsyncMock, MagicMock]:
    gw = _mock_gateway(response_text)
    cb = _mock_context_builder()
    uc = GenerateQuizUseCase(model_gateway=gw, context_builder=cb)
    return uc, gw, cb


# ---------------------------------------------------------------------------
# No evidence — early exit
# ---------------------------------------------------------------------------


class TestNoEvidence:
    async def test_returns_no_material_message_without_calling_gateway(self) -> None:
        uc, gw, _ = _make_use_case()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[])
        result = await uc.execute(cmd)
        assert result.text == _NO_MATERIAL_MESSAGE
        gw.generate.assert_not_called()

    async def test_returns_quiz_result_type(self) -> None:
        uc, _, _ = _make_use_case()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[])
        result = await uc.execute(cmd)
        assert isinstance(result, QuizResult)


# ---------------------------------------------------------------------------
# Evidence conversion
# ---------------------------------------------------------------------------


class TestEvidenceConversion:
    async def test_evidence_converted_to_labeled_passages(self) -> None:
        uc, gw, cb = _make_use_case()
        ev = _mock_evidence(label="S3", text="Newton's laws of motion.")
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[ev])
        await uc.execute(cmd)

        cb.build.assert_called_once()
        inputs: ContextInputs = cb.build.call_args[0][0]
        assert len(inputs.evidence) == 1
        assert inputs.evidence[0].label == "[S3]"
        assert inputs.evidence[0].text == UntrustedText("Newton's laws of motion.")

    async def test_multiple_evidence_items_all_converted(self) -> None:
        uc, _, cb = _make_use_case()
        evidence = [
            _mock_evidence(label="S1", text="passage one"),
            _mock_evidence(label="S2", text="passage two"),
        ]
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=evidence)
        await uc.execute(cmd)

        inputs: ContextInputs = cb.build.call_args[0][0]
        assert len(inputs.evidence) == 2
        labels = [p.label for p in inputs.evidence]
        assert "[S1]" in labels
        assert "[S2]" in labels


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    async def test_uses_quiz_generation_model_task(self) -> None:
        uc, _, cb = _make_use_case()
        ev = _mock_evidence()
        cmd = GenerateQuizCommand(scope=_scope(), query="test me on thermodynamics", evidence=[ev])
        await uc.execute(cmd)

        inputs: ContextInputs = cb.build.call_args[0][0]
        assert inputs.model_task is ModelTask.QUIZ_GENERATION

    async def test_query_passed_into_context_inputs(self) -> None:
        uc, _, cb = _make_use_case()
        ev = _mock_evidence()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me on chapter 3", evidence=[ev])
        await uc.execute(cmd)

        inputs: ContextInputs = cb.build.call_args[0][0]
        assert inputs.query == "quiz me on chapter 3"

    async def test_conversation_history_forwarded(self) -> None:
        uc, _, cb = _make_use_case()
        ev = _mock_evidence()
        history_turn = MagicMock()
        cmd = GenerateQuizCommand(
            scope=_scope(),
            query="quiz me",
            evidence=[ev],
            history=(history_turn,),
        )
        await uc.execute(cmd)

        inputs: ContextInputs = cb.build.call_args[0][0]
        assert history_turn in inputs.conversation_history


# ---------------------------------------------------------------------------
# Gateway call and result
# ---------------------------------------------------------------------------


class TestGatewayResult:
    async def test_returns_model_response_as_quiz_text(self) -> None:
        quiz_text = "1. What is entropy?\n   Answer: A measure of disorder."
        uc, _, _ = _make_use_case(response_text=quiz_text)
        ev = _mock_evidence()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[ev])
        result = await uc.execute(cmd)
        assert result.text == quiz_text

    async def test_strips_leading_trailing_whitespace_from_response(self) -> None:
        uc, _, _ = _make_use_case(response_text="   1. Q?\n   Answer: A.   ")
        ev = _mock_evidence()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[ev])
        result = await uc.execute(cmd)
        assert result.text == "1. Q?\n   Answer: A."

    async def test_empty_model_response_returns_no_material_message(self) -> None:
        uc, _, _ = _make_use_case(response_text="")
        ev = _mock_evidence()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[ev])
        result = await uc.execute(cmd)
        assert result.text == _NO_MATERIAL_MESSAGE

    async def test_whitespace_only_response_returns_no_material_message(self) -> None:
        uc, _, _ = _make_use_case(response_text="   \n  ")
        ev = _mock_evidence()
        cmd = GenerateQuizCommand(scope=_scope(), query="quiz me", evidence=[ev])
        result = await uc.execute(cmd)
        assert result.text == _NO_MATERIAL_MESSAGE
