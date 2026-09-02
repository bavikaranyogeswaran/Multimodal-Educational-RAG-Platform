"""Unit tests for model warm-up at startup.

Verifies that warm_up_models sends exactly one generate call with a minimal request
and that any failure is swallowed rather than propagated.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.domain.enums import ModelTask
from app.domain.errors import ProviderError
from app.infrastructure.models.warmup import warm_up_models


def _gateway(*, side_effect: Exception | None = None) -> MagicMock:
    gw = MagicMock()
    gw.generate = AsyncMock(side_effect=side_effect)
    return gw


class TestWarmUpModels:
    async def test_calls_generate_once(self) -> None:
        gw = _gateway()
        await warm_up_models(gw)
        gw.generate.assert_awaited_once()

    async def test_request_targets_answer_generation(self) -> None:
        gw = _gateway()
        await warm_up_models(gw)
        request = gw.generate.call_args[0][0]
        assert request.model_task is ModelTask.ANSWER_GENERATION

    async def test_request_caps_output_at_one_token(self) -> None:
        gw = _gateway()
        await warm_up_models(gw)
        request = gw.generate.call_args[0][0]
        assert request.max_tokens == 1

    async def test_request_uses_zero_temperature(self) -> None:
        gw = _gateway()
        await warm_up_models(gw)
        request = gw.generate.call_args[0][0]
        assert request.temperature == 0.0

    async def test_request_carries_no_private_content(self) -> None:
        gw = _gateway()
        await warm_up_models(gw)
        request = gw.generate.call_args[0][0]
        assert request.privacy_sensitive is False

    async def test_provider_error_does_not_propagate(self) -> None:
        gw = _gateway(side_effect=ProviderError("ollama", "offline", retryable=True))
        await warm_up_models(gw)  # must not raise

    async def test_connection_error_does_not_propagate(self) -> None:
        gw = _gateway(side_effect=OSError("connection refused"))
        await warm_up_models(gw)  # must not raise

    async def test_arbitrary_exception_does_not_propagate(self) -> None:
        gw = _gateway(side_effect=RuntimeError("unexpected"))
        await warm_up_models(gw)  # must not raise
