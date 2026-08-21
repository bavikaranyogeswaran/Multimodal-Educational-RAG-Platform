"""Unit tests for the OpenAI-compatible model gateway adapter.

Verifies the non-streaming (generate) path, the SSE streaming path, error
mapping, the token stream protocol, and the profile contract.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest
from app.infrastructure.models.providers.openai_compat import (
    OpenAICompatTokenStream,
    OpenAICompatibleGateway,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gateway(
    *,
    model_id: str = "gpt-test",
    data_boundary: DataBoundary = DataBoundary.THIRD_PARTY,
    api_key: str = "",
    timeout_seconds: int = 30,
) -> tuple[OpenAICompatibleGateway, MagicMock]:
    client = MagicMock(spec=httpx.AsyncClient)
    gateway = OpenAICompatibleGateway(
        http_client=client,
        model_id=model_id,
        timeout_seconds=timeout_seconds,
        data_boundary=data_boundary,
        api_key=api_key,
    )
    return gateway, client


def _minimal_request() -> ModelRequest:
    return ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="You are a tutor.",
        safety_rules=(),
        task_instructions="Answer concisely.",
        query="What is photosynthesis?",
    )


def _ok_response(content: str = "hello", prompt_tokens: int = 5, completion_tokens: int = 3) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = {
        "choices": [
            {"message": {"content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    resp.raise_for_status = MagicMock()
    return resp


async def _sse_lines(*chunks: dict, done: bool = True) -> AsyncIterator[str]:
    """Yield SSE data lines from dicts, then [DONE]."""
    for chunk in chunks:
        yield f"data: {json.dumps(chunk)}"
    if done:
        yield "data: [DONE]"


# ---------------------------------------------------------------------------
# Profile contract
# ---------------------------------------------------------------------------

class TestProfile:
    def test_profile_carries_configured_model_id(self) -> None:
        gw, _ = _make_gateway(model_id="gpt-4o")
        assert gw.profile.model_key == "gpt-4o"

    def test_profile_carries_data_boundary(self) -> None:
        gw, _ = _make_gateway(data_boundary=DataBoundary.THIRD_PARTY)
        assert gw.profile.data_boundary is DataBoundary.THIRD_PARTY

    def test_profile_supports_answer_generation(self) -> None:
        gw, _ = _make_gateway()
        assert gw.profile.supports_task(ModelTask.ANSWER_GENERATION)

    def test_profile_for_raises_on_unsupported_task(self) -> None:
        gw, _ = _make_gateway()
        with pytest.raises(UnsupportedCapabilityError):
            gw.profile_for(MagicMock(spec=ModelTask, value="unsupported_task"))

    async def test_generate_with_image_raises(self) -> None:
        gw, _ = _make_gateway()
        with pytest.raises(UnsupportedCapabilityError):
            await gw.generate_with_image(_minimal_request(), b"fake")


# ---------------------------------------------------------------------------
# generate() — happy path
# ---------------------------------------------------------------------------

class TestGenerate:
    async def test_posts_to_chat_completions_endpoint(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response())
        await gw.generate(_minimal_request())
        client.post.assert_awaited_once()
        url_arg = client.post.call_args[0][0]
        assert url_arg == "/v1/chat/completions"

    async def test_payload_includes_model_id(self) -> None:
        gw, client = _make_gateway(model_id="gpt-4o-mini")
        client.post = AsyncMock(return_value=_ok_response())
        await gw.generate(_minimal_request())
        payload = client.post.call_args.kwargs["json"]
        assert payload["model"] == "gpt-4o-mini"

    async def test_payload_sets_stream_false(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response())
        await gw.generate(_minimal_request())
        payload = client.post.call_args.kwargs["json"]
        assert payload["stream"] is False

    async def test_payload_includes_messages(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response())
        await gw.generate(_minimal_request())
        payload = client.post.call_args.kwargs["json"]
        assert isinstance(payload["messages"], list)
        assert len(payload["messages"]) >= 1

    async def test_response_content_is_mapped(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response(content="Photosynthesis converts light."))
        result = await gw.generate(_minimal_request())
        assert result.content.value == "Photosynthesis converts light."

    async def test_response_token_counts_are_mapped(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response(prompt_tokens=10, completion_tokens=7))
        result = await gw.generate(_minimal_request())
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 7

    async def test_max_tokens_forwarded_in_payload(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response())
        request = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble="sys",
            safety_rules=(),
            task_instructions="task",
            query="q",
            max_tokens=128,
        )
        await gw.generate(request)
        payload = client.post.call_args.kwargs["json"]
        assert payload["max_tokens"] == 128

    async def test_temperature_forwarded_in_payload(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(return_value=_ok_response())
        request = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble="sys",
            safety_rules=(),
            task_instructions="task",
            query="q",
            temperature=0.7,
        )
        await gw.generate(request)
        payload = client.post.call_args.kwargs["json"]
        assert payload["temperature"] == 0.7

    async def test_api_key_sent_as_bearer(self) -> None:
        gw, client = _make_gateway(api_key="sk-test")
        client.post = AsyncMock(return_value=_ok_response())
        await gw.generate(_minimal_request())
        headers = client.post.call_args.kwargs["headers"]
        assert headers.get("Authorization") == "Bearer sk-test"

    async def test_no_auth_header_when_api_key_empty(self) -> None:
        gw, client = _make_gateway(api_key="")
        client.post = AsyncMock(return_value=_ok_response())
        await gw.generate(_minimal_request())
        headers = client.post.call_args.kwargs["headers"]
        assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# generate() — error mapping
# ---------------------------------------------------------------------------

class TestGenerateErrors:
    async def test_5xx_raises_retryable_provider_error(self) -> None:
        gw, client = _make_gateway()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 503
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=resp
        )
        client.post = AsyncMock(return_value=resp)
        with pytest.raises(ProviderError) as exc_info:
            await gw.generate(_minimal_request())
        assert exc_info.value.retryable is True

    async def test_4xx_raises_non_retryable_provider_error(self) -> None:
        gw, client = _make_gateway()
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=resp
        )
        client.post = AsyncMock(return_value=resp)
        with pytest.raises(ProviderError) as exc_info:
            await gw.generate(_minimal_request())
        assert exc_info.value.retryable is False

    async def test_network_error_raises_retryable_provider_error(self) -> None:
        gw, client = _make_gateway()
        client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(ProviderError) as exc_info:
            await gw.generate(_minimal_request())
        assert exc_info.value.retryable is True


# ---------------------------------------------------------------------------
# generate_stream() / OpenAICompatTokenStream
# ---------------------------------------------------------------------------

class TestGenerateStream:
    async def test_stream_yields_content_tokens(self) -> None:
        chunk1 = {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]}
        chunk2 = {"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]}
        stream = OpenAICompatTokenStream(_sse_lines(chunk1, chunk2), "gpt-test")
        tokens = [t async for t in stream]
        assert tokens == ["Hello", " world"]

    async def test_stream_skips_blank_delta(self) -> None:
        chunk_with_role = {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}
        chunk_with_content = {"choices": [{"delta": {"content": "Hi"}, "finish_reason": "stop"}]}
        stream = OpenAICompatTokenStream(
            _sse_lines(chunk_with_role, chunk_with_content), "gpt-test"
        )
        tokens = [t async for t in stream]
        assert tokens == ["Hi"]

    async def test_stream_usage_is_none_before_exhaustion(self) -> None:
        chunk = {"choices": [{"delta": {"content": "x"}, "finish_reason": None}]}
        stream = OpenAICompatTokenStream(_sse_lines(chunk), "gpt-test")
        assert stream.usage is None

    async def test_stream_usage_populated_after_exhaustion(self) -> None:
        chunk_with_usage = {
            "choices": [{"delta": {"content": "ans"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        }
        stream = OpenAICompatTokenStream(_sse_lines(chunk_with_usage), "gpt-test")
        _ = [t async for t in stream]
        assert stream.usage is not None
        assert stream.usage.prompt_tokens == 8
        assert stream.usage.completion_tokens == 3

    async def test_stream_skips_non_data_lines(self) -> None:
        async def lines_with_noise() -> AsyncIterator[str]:
            yield ": keep-alive"
            yield ""
            yield 'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}'
            yield "data: [DONE]"

        stream = OpenAICompatTokenStream(lines_with_noise(), "gpt-test")
        tokens = [t async for t in stream]
        assert tokens == ["ok"]

    async def test_stream_payload_sets_stream_true(self) -> None:
        """generate_stream must request stream:true so the server sends SSE."""
        gw, client = _make_gateway()

        captured_payload: dict = {}

        async def aiter_done() -> AsyncIterator[str]:
            yield "data: [DONE]"

        # httpx.stream() is a regular method (not a coroutine); it returns an async CM.
        def fake_stream_cm(method: str, url: str, *, json: dict, headers: dict, timeout: int):
            nonlocal captured_payload
            captured_payload = json
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                raise_for_status=MagicMock(),
                aiter_lines=MagicMock(return_value=aiter_done()),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        client.stream = fake_stream_cm

        stream = gw.generate_stream(_minimal_request())
        _ = [t async for t in stream]
        assert captured_payload.get("stream") is True

    async def test_stream_payload_includes_stream_options(self) -> None:
        """generate_stream must request include_usage so the token count arrives."""
        gw, client = _make_gateway()

        captured_payload: dict = {}

        async def aiter_done() -> AsyncIterator[str]:
            yield "data: [DONE]"

        def fake_stream_cm(method: str, url: str, *, json: dict, headers: dict, timeout: int):
            nonlocal captured_payload
            captured_payload = json
            cm = MagicMock()
            cm.__aenter__ = AsyncMock(return_value=MagicMock(
                raise_for_status=MagicMock(),
                aiter_lines=MagicMock(return_value=aiter_done()),
            ))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        client.stream = fake_stream_cm

        stream = gw.generate_stream(_minimal_request())
        _ = [t async for t in stream]
        assert captured_payload.get("stream_options", {}).get("include_usage") is True
