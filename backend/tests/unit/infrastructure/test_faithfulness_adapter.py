"""Unit tests for OllamaAnswerFaithfulness.

All tests use a mock ModelGatewayPort — no real Ollama server is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import AnswerFidelity, ModelTask
from app.domain.errors import GenerationParseError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.models.generation import Claim, GeneratedAnswer
from app.domain.values import UntrustedText
from app.infrastructure.models.faithfulness import OllamaAnswerFaithfulness

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(response_text: str = "FAITHFUL") -> MagicMock:
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=ModelResponse(
            model_task=ModelTask.FAITHFULNESS_CHECK,
            model_id="test-model",
            content=UntrustedText(response_text),
            prompt_tokens=40,
            completion_tokens=1,
        )
    )
    return gateway


def _answer(
    *claims: Claim,
    text: str = "Gradients flow backwards through the network.",
) -> GeneratedAnswer:
    supplied = claims or (
        Claim(text="Gradients flow backwards.", citations=("[S1]",)),
    )
    return GeneratedAnswer(answer=text, claims=supplied)


def _request(gateway: MagicMock) -> ModelRequest:
    result: ModelRequest = gateway.generate.call_args.args[0]
    return result


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


class TestVerdicts:
    async def test_returns_faithful(self) -> None:
        gateway = _make_gateway("FAITHFUL")
        result = await OllamaAnswerFaithfulness(gateway).check_answer(_answer())
        assert result is AnswerFidelity.FAITHFUL

    async def test_returns_overstated(self) -> None:
        gateway = _make_gateway("OVERSTATED")
        result = await OllamaAnswerFaithfulness(gateway).check_answer(_answer())
        assert result is AnswerFidelity.OVERSTATED

    async def test_tolerates_surrounding_whitespace_and_case(self) -> None:
        gateway = _make_gateway("  overstated \n")
        result = await OllamaAnswerFaithfulness(gateway).check_answer(_answer())
        assert result is AnswerFidelity.OVERSTATED

    async def test_an_unreadable_verdict_raises_rather_than_guessing(self) -> None:
        gateway = _make_gateway("probably fine")
        with pytest.raises(GenerationParseError):
            await OllamaAnswerFaithfulness(gateway).check_answer(_answer())


# ---------------------------------------------------------------------------
# What the request carries
# ---------------------------------------------------------------------------


class TestRequestShape:
    async def test_sends_the_answer_and_its_claims(self) -> None:
        gateway = _make_gateway()
        answer = _answer(
            Claim(text="A cited fact.", citations=("[S1]",)),
            text="A cited fact, explained at length.",
        )

        await OllamaAnswerFaithfulness(gateway).check_answer(answer)

        assert "A cited fact, explained at length." in _request(gateway).query
        assert "A cited fact." in _request(gateway).query

    async def test_carries_no_evidence(self) -> None:
        """A passage in context invites the model to find support the claims never made,
        which is the exact failure this check exists to catch."""
        gateway = _make_gateway()

        await OllamaAnswerFaithfulness(gateway).check_answer(_answer())

        request = _request(gateway)
        assert request.evidence == ()
        assert request.conversation_history == ()
        assert request.pinned_memory == ()

    async def test_runs_as_a_faithfulness_check(self) -> None:
        gateway = _make_gateway()
        await OllamaAnswerFaithfulness(gateway).check_answer(_answer())
        assert _request(gateway).model_task is ModelTask.FAITHFULNESS_CHECK

    async def test_asks_for_a_one_word_answer(self) -> None:
        gateway = _make_gateway()
        await OllamaAnswerFaithfulness(gateway).check_answer(_answer())
        request = _request(gateway)
        assert request.output_schema is not None
        assert "FAITHFUL" in request.output_schema
        assert request.max_tokens == 10


# ---------------------------------------------------------------------------
# Short circuit
# ---------------------------------------------------------------------------


class TestNoClaims:
    async def test_an_answer_with_no_claims_is_faithful_without_a_model_call(self) -> None:
        """There is nothing to overstate against, so the call could only ever return one
        value — and a model call with one possible answer is worth not making."""
        gateway = _make_gateway()
        answer = GeneratedAnswer(
            answer="The passages do not cover this.", claims=(), insufficient_evidence=True
        )

        result = await OllamaAnswerFaithfulness(gateway).check_answer(answer)

        assert result is AnswerFidelity.FAITHFUL
        gateway.generate.assert_not_called()
