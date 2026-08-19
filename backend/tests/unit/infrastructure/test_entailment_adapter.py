"""Unit tests for OllamaClaimEntailment.

All tests use a mock ModelGatewayPort — no real Ollama server is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import ClaimStatus, ModelTask
from app.domain.errors import GenerationParseError
from app.domain.models.entities import LabeledPassage
from app.domain.models.generation import Claim
from app.domain.values import UntrustedText
from app.infrastructure.models.entailment import OllamaClaimEntailment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(response_text: str = "ENTAILED") -> MagicMock:
    from app.domain.models.entities import ModelResponse

    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=ModelResponse(
            model_task=ModelTask.FAITHFULNESS_CHECK,
            model_id="test-model",
            content=UntrustedText(response_text),
            prompt_tokens=10,
            completion_tokens=1,
        )
    )
    return gateway


def _passage(label: str, text: str = "A reference passage.") -> LabeledPassage:
    return LabeledPassage(label=label, text=UntrustedText(text))


def _claim(
    text: str = "Backpropagation computes gradients.",
    citations: tuple[str, ...] = ("[S1]",),
) -> Claim:
    return Claim(text=text, citations=citations)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOllamaClaimEntailment:
    async def test_returns_one_result_per_passage(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        claim = _claim()
        passages = [_passage("[S1]"), _passage("[S2]")]
        results = await adapter.check_claim(claim, passages)
        assert len(results) == 2

    async def test_result_carries_claim(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        claim = _claim()
        results = await adapter.check_claim(claim, [_passage("[S1]")])
        assert results[0].claim is claim

    async def test_result_carries_passage_label(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [_passage("[S2]")])
        assert results[0].passage_label == "[S2]"

    async def test_entailed_status_parsed(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [_passage("[S1]")])
        assert results[0].status is ClaimStatus.ENTAILED

    async def test_contradicted_status_parsed(self) -> None:
        gateway = _make_gateway("CONTRADICTED")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [_passage("[S1]")])
        assert results[0].status is ClaimStatus.CONTRADICTED

    async def test_not_supported_status_parsed(self) -> None:
        gateway = _make_gateway("NOT_SUPPORTED")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [_passage("[S1]")])
        assert results[0].status is ClaimStatus.NOT_SUPPORTED

    async def test_gateway_called_once_per_passage(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        await adapter.check_claim(_claim(), [_passage("[S1]"), _passage("[S2]"), _passage("[S3]")])
        assert gateway.generate.await_count == 3

    async def test_request_uses_faithfulness_check_task(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        await adapter.check_claim(_claim(), [_passage("[S1]")])
        request = gateway.generate.call_args.args[0]
        assert request.model_task is ModelTask.FAITHFULNESS_CHECK

    async def test_request_query_contains_claim_text(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        claim = _claim(text="A specific factual statement.")
        await adapter.check_claim(claim, [_passage("[S1]", text="A passage.")])
        request = gateway.generate.call_args.args[0]
        assert "A specific factual statement." in request.query

    async def test_request_query_contains_passage_text(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        await adapter.check_claim(_claim(), [_passage("[S1]", text="Unique passage content.")])
        request = gateway.generate.call_args.args[0]
        assert "Unique passage content." in request.query

    async def test_request_query_contains_passage_label(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        await adapter.check_claim(_claim(), [_passage("[S7]")])
        request = gateway.generate.call_args.args[0]
        assert "[S7]" in request.query

    async def test_request_has_output_schema(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        await adapter.check_claim(_claim(), [_passage("[S1]")])
        request = gateway.generate.call_args.args[0]
        assert request.output_schema is not None

    async def test_request_has_low_max_tokens(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        await adapter.check_claim(_claim(), [_passage("[S1]")])
        request = gateway.generate.call_args.args[0]
        assert request.max_tokens is not None
        assert request.max_tokens <= 20

    async def test_empty_passages_returns_empty_tuple(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [])
        assert results == ()
        gateway.generate.assert_not_awaited()

    async def test_returns_tuple_not_list(self) -> None:
        gateway = _make_gateway("ENTAILED")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [_passage("[S1]")])
        assert isinstance(results, tuple)

    async def test_unrecognised_response_raises(self) -> None:
        gateway = _make_gateway("MAYBE")
        adapter = OllamaClaimEntailment(gateway)
        with pytest.raises(GenerationParseError):
            await adapter.check_claim(_claim(), [_passage("[S1]")])

    async def test_each_call_sends_only_one_passage(self) -> None:
        responses = ["ENTAILED", "NOT_SUPPORTED"]
        call_idx = 0

        async def _respond(request):  # type: ignore[no-untyped-def]
            nonlocal call_idx
            from app.domain.models.entities import ModelResponse
            text = responses[call_idx]
            call_idx += 1
            return ModelResponse(
                model_task=ModelTask.FAITHFULNESS_CHECK,
                model_id="test",
                content=UntrustedText(text),
                prompt_tokens=5,
                completion_tokens=1,
            )

        gateway = MagicMock()
        gateway.generate = AsyncMock(side_effect=_respond)
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(
            _claim(), [_passage("[S1]", "First."), _passage("[S2]", "Second.")]
        )
        assert results[0].status is ClaimStatus.ENTAILED
        assert results[1].status is ClaimStatus.NOT_SUPPORTED
        assert results[0].passage_label == "[S1]"
        assert results[1].passage_label == "[S2]"

    async def test_whitespace_in_response_tolerated(self) -> None:
        gateway = _make_gateway("  ENTAILED\n")
        adapter = OllamaClaimEntailment(gateway)
        results = await adapter.check_claim(_claim(), [_passage("[S1]")])
        assert results[0].status is ClaimStatus.ENTAILED
