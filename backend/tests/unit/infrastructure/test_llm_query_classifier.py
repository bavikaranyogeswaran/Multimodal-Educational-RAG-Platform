"""Integration tests for LlmQueryClassifier.

Wires the real adapter against a stub model gateway and verifies that the
classification, parse, and fallback paths all behave correctly without a
live model server.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.enums import ModelTask, QueryClass
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.values import UntrustedText
from app.infrastructure.multi_hop.classifier import LlmQueryClassifier, _parse


# ---------------------------------------------------------------------------
# Stub gateway
# ---------------------------------------------------------------------------


class _StubGateway:
    """Returns a fixed text response for every generate() call."""

    def __init__(self, response_text: str) -> None:
        self.calls: list[ModelTask] = []
        self._text = response_text

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request.model_task)
        return ModelResponse(
            model_task=request.model_task,
            model_id="stub",
            content=UntrustedText(self._text),
            prompt_tokens=5,
            completion_tokens=2,
            finish_reason="stop",
            latency_ms=1,
        )


class _FailingGateway:
    """Always raises on generate() to test the error-fallback path."""

    async def generate(self, request: ModelRequest) -> ModelResponse:
        raise RuntimeError("gateway unavailable")


# ---------------------------------------------------------------------------
# Unit tests for _parse (no gateway needed)
# ---------------------------------------------------------------------------


class TestParse:
    def test_exact_match(self) -> None:
        assert _parse("MULTI_HOP", "q") is QueryClass.MULTI_HOP

    def test_lowercase_accepted(self) -> None:
        assert _parse("comparison", "q") is QueryClass.COMPARISON

    def test_mixed_case_accepted(self) -> None:
        assert _parse("Exact_Term", "q") is QueryClass.EXACT_TERM

    def test_trailing_period_stripped(self) -> None:
        assert _parse("SUMMARY.", "q") is QueryClass.SUMMARY

    def test_leading_whitespace_stripped(self) -> None:
        assert _parse("  VISUAL", "q") is QueryClass.VISUAL

    def test_first_valid_token_wins(self) -> None:
        assert _parse("AGGREGATION extra words", "q") is QueryClass.AGGREGATION

    def test_unrecognised_falls_back_to_direct(self) -> None:
        assert _parse("UNKNOWN_CLASS", "q") is QueryClass.DIRECT

    def test_empty_string_falls_back_to_direct(self) -> None:
        assert _parse("", "q") is QueryClass.DIRECT


# ---------------------------------------------------------------------------
# Integration tests against stub gateway
# ---------------------------------------------------------------------------


class TestLlmQueryClassifier:
    async def test_calls_query_classification_task(self) -> None:
        gw = _StubGateway("DIRECT")
        clf = LlmQueryClassifier(gw)
        await clf.classify("what is photosynthesis?")
        assert gw.calls == [ModelTask.QUERY_CLASSIFICATION]

    async def test_returns_parsed_query_class(self) -> None:
        gw = _StubGateway("MULTI_HOP")
        clf = LlmQueryClassifier(gw)
        result = await clf.classify("trace the chain of events from X to Y")
        assert result is QueryClass.MULTI_HOP

    async def test_comparison_class_returned(self) -> None:
        gw = _StubGateway("COMPARISON")
        clf = LlmQueryClassifier(gw)
        result = await clf.classify("compare osmosis and diffusion")
        assert result is QueryClass.COMPARISON

    async def test_gateway_error_returns_direct(self) -> None:
        clf = LlmQueryClassifier(_FailingGateway())
        result = await clf.classify("some query")
        assert result is QueryClass.DIRECT

    async def test_unrecognised_model_output_returns_direct(self) -> None:
        gw = _StubGateway("I cannot classify this.")
        clf = LlmQueryClassifier(gw)
        result = await clf.classify("what is X?")
        assert result is QueryClass.DIRECT

    async def test_all_thirteen_classes_parseable(self) -> None:
        for qc in QueryClass:
            gw = _StubGateway(qc.value)
            clf = LlmQueryClassifier(gw)
            result = await clf.classify("query")
            assert result is qc, f"Failed for {qc}"
