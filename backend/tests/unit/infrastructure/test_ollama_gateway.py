"""Unit tests for OllamaModelGateway.

All tests use a mock httpx.AsyncClient — no real Ollama server is required.
Tests verify:
  - Prompt assembly (7-slot ModelRequest → Ollama messages array)
  - HTTP payload structure (model, stream, options)
  - Response mapping (content, tokens, finish_reason, latency)
  - Error translation (HTTP 4xx/5xx → ProviderError, network → ProviderError)
  - Unsupported capability for image input
  - Profile routing
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.domain.enums import DataBoundary, MessageRole, ModelTask
from app.domain.errors import ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import ConversationTurn, ModelRequest
from app.domain.values import UntrustedText
from app.infrastructure.models.providers.ollama import OllamaModelGateway, _build_messages

# ---------------------------------------------------------------------------
# Fixtures and factories
# ---------------------------------------------------------------------------


def _make_request(
    *,
    task: ModelTask = ModelTask.ANSWER_GENERATION,
    preamble: str = "You are a helpful tutor.",
    safety_rules: tuple[str, ...] = (),
    instructions: str = "Answer the student's question.",
    memory: tuple[str, ...] = (),
    evidence: tuple[UntrustedText, ...] = (),
    history: tuple[ConversationTurn, ...] = (),
    query: str = "What is photosynthesis?",
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> ModelRequest:
    return ModelRequest(
        model_task=task,
        system_preamble=preamble,
        safety_rules=safety_rules,
        task_instructions=instructions,
        memory_context=memory,
        evidence=evidence,
        conversation_history=history,
        query=query,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _make_response_json(
    content: str = "Photosynthesis is...",
    done_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> dict:
    return {
        "model": "gemma3:4b",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
    }


def _mock_client(response_json: dict | None = None) -> AsyncMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = response_json or _make_response_json()

    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(return_value=mock_resp)
    return client


def _gateway(client: AsyncMock, model_id: str = "gemma3:4b") -> OllamaModelGateway:
    return OllamaModelGateway(http_client=client, model_id=model_id, timeout_seconds=30)


# ---------------------------------------------------------------------------
# HTTP payload structure
# ---------------------------------------------------------------------------


class TestHttpPayload:
    async def test_posts_to_api_chat(self) -> None:
        client = _mock_client()
        await _gateway(client).generate(_make_request())
        url = client.post.call_args.args[0]
        assert url == "/api/chat"

    async def test_includes_model_id(self) -> None:
        client = _mock_client()
        await _gateway(client, model_id="llama3:8b").generate(_make_request())
        payload = client.post.call_args.kwargs["json"]
        assert payload["model"] == "llama3:8b"

    async def test_stream_is_false(self) -> None:
        client = _mock_client()
        await _gateway(client).generate(_make_request())
        payload = client.post.call_args.kwargs["json"]
        assert payload["stream"] is False

    async def test_max_tokens_maps_to_num_predict(self) -> None:
        client = _mock_client()
        await _gateway(client).generate(_make_request(max_tokens=512))
        payload = client.post.call_args.kwargs["json"]
        assert payload["options"]["num_predict"] == 512

    async def test_temperature_sent_in_options(self) -> None:
        client = _mock_client()
        await _gateway(client).generate(_make_request(temperature=0.7))
        payload = client.post.call_args.kwargs["json"]
        assert payload["options"]["temperature"] == pytest.approx(0.7)

    async def test_no_options_key_when_defaults_used(self) -> None:
        client = _mock_client()
        await _gateway(client).generate(_make_request())
        payload = client.post.call_args.kwargs["json"]
        assert "options" not in payload

    async def test_timeout_passed_to_client(self) -> None:
        client = _mock_client()
        await OllamaModelGateway(
            http_client=client, model_id="gemma3:4b", timeout_seconds=60
        ).generate(_make_request())
        timeout = client.post.call_args.kwargs["timeout"]
        assert timeout == 60


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


class TestPromptAssembly:
    def test_system_message_is_first(self) -> None:
        req = _make_request(preamble="P", instructions="I")
        msgs = _build_messages(req)
        assert msgs[0]["role"] == "system"

    def test_system_contains_preamble(self) -> None:
        req = _make_request(preamble="I am a tutor.")
        msgs = _build_messages(req)
        assert "I am a tutor." in msgs[0]["content"]

    def test_system_contains_safety_rules(self) -> None:
        req = _make_request(safety_rules=("Never invent citations.",))
        msgs = _build_messages(req)
        assert "Never invent citations." in msgs[0]["content"]

    def test_system_contains_task_instructions(self) -> None:
        req = _make_request(instructions="Be concise.")
        msgs = _build_messages(req)
        assert "Be concise." in msgs[0]["content"]

    def test_query_is_last_user_message(self) -> None:
        req = _make_request(query="Explain osmosis.")
        msgs = _build_messages(req)
        assert msgs[-1] == {"role": "user", "content": "Explain osmosis."}

    def test_memory_context_injected_as_user_turn(self) -> None:
        req = _make_request(memory=("Student prefers examples.", "First year student."))
        msgs = _build_messages(req)
        roles = [m["role"] for m in msgs]
        content = " ".join(m["content"] for m in msgs)
        assert "Student prefers examples." in content
        assert "First year student." in content
        assert "assistant" in roles  # acknowledgement turn

    def test_evidence_injected_as_user_turn(self) -> None:
        ev = UntrustedText("Photosynthesis is the process of converting light into energy.")
        req = _make_request(evidence=(ev,))
        msgs = _build_messages(req)
        joined = " ".join(m["content"] for m in msgs)
        assert ev.value in joined

    def test_evidence_uses_value_not_str_repr(self) -> None:
        ev = UntrustedText("Some evidence.")
        req = _make_request(evidence=(ev,))
        msgs = _build_messages(req)
        joined = " ".join(m["content"] for m in msgs)
        assert "untrusted text" not in joined.lower()
        assert "Some evidence." in joined

    def test_conversation_history_preserves_order(self) -> None:
        history = (
            ConversationTurn(role=MessageRole.USER, content=UntrustedText("Hello.")),
            ConversationTurn(role=MessageRole.ASSISTANT, content=UntrustedText("Hi there.")),
        )
        req = _make_request(history=history)
        msgs = _build_messages(req)
        user_msgs = [m for m in msgs if m["role"] == "user"]
        assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert any("Hello." in m["content"] for m in user_msgs)
        assert any("Hi there." in m["content"] for m in assistant_msgs)

    def test_no_memory_turn_when_empty(self) -> None:
        req = _make_request(memory=())
        msgs = _build_messages(req)
        content = " ".join(m["content"] for m in msgs)
        assert "Student context" not in content

    def test_no_evidence_turn_when_empty(self) -> None:
        req = _make_request(evidence=())
        msgs = _build_messages(req)
        content = " ".join(m["content"] for m in msgs)
        assert "Reference material" not in content


# ---------------------------------------------------------------------------
# Response mapping
# ---------------------------------------------------------------------------


class TestResponseMapping:
    async def test_content_comes_from_message_content(self) -> None:
        client = _mock_client(_make_response_json(content="The answer is 42."))
        result = await _gateway(client).generate(_make_request())
        assert result.content.value == "The answer is 42."

    async def test_prompt_tokens_from_prompt_eval_count(self) -> None:
        client = _mock_client(_make_response_json(prompt_tokens=200))
        result = await _gateway(client).generate(_make_request())
        assert result.prompt_tokens == 200

    async def test_completion_tokens_from_eval_count(self) -> None:
        client = _mock_client(_make_response_json(completion_tokens=75))
        result = await _gateway(client).generate(_make_request())
        assert result.completion_tokens == 75

    async def test_finish_reason_from_done_reason(self) -> None:
        client = _mock_client(_make_response_json(done_reason="length"))
        result = await _gateway(client).generate(_make_request())
        assert result.finish_reason == "length"

    async def test_model_task_preserved_in_response(self) -> None:
        client = _mock_client()
        result = await _gateway(client).generate(_make_request(task=ModelTask.QUERY_REWRITE))
        assert result.model_task is ModelTask.QUERY_REWRITE

    async def test_model_id_in_response(self) -> None:
        client = _mock_client()
        result = await _gateway(client, model_id="gemma3:4b").generate(_make_request())
        assert result.model_id == "gemma3:4b"

    async def test_latency_ms_is_non_negative(self) -> None:
        client = _mock_client()
        result = await _gateway(client).generate(_make_request())
        assert result.latency_ms is not None
        assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_http_5xx_raises_retryable_provider_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_resp
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ProviderError) as exc_info:
            await _gateway(client).generate(_make_request())

        assert exc_info.value.retryable is True

    async def test_http_4xx_raises_non_retryable_provider_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_resp
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(ProviderError) as exc_info:
            await _gateway(client).generate(_make_request())

        assert exc_info.value.retryable is False

    async def test_request_error_raises_retryable_provider_error(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with pytest.raises(ProviderError) as exc_info:
            await _gateway(client).generate(_make_request())

        assert exc_info.value.retryable is True

    async def test_provider_is_ollama_in_error(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(ProviderError) as exc_info:
            await _gateway(client).generate(_make_request())

        assert exc_info.value.provider == "ollama"


# ---------------------------------------------------------------------------
# Image and profile
# ---------------------------------------------------------------------------


class TestCapabilities:
    async def test_generate_with_image_raises_unsupported(self) -> None:
        client = _mock_client()
        with pytest.raises(UnsupportedCapabilityError):
            await _gateway(client).generate_with_image(_make_request(), b"\x89PNG")

    def test_profile_for_returns_profile_for_text_task(self) -> None:
        client = _mock_client()
        gw = _gateway(client)
        profile = gw.profile_for(ModelTask.ANSWER_GENERATION)
        assert profile.model_key == "gemma3:4b"

    def test_profile_for_raises_for_visual_task(self) -> None:
        client = _mock_client()
        gw = _gateway(client)
        with pytest.raises(UnsupportedCapabilityError):
            gw.profile_for(ModelTask.VISUAL_QUESTION)

    def test_profile_data_boundary_is_local(self) -> None:
        client = _mock_client()
        assert _gateway(client).profile.data_boundary is DataBoundary.LOCAL

    def test_profile_supports_images_is_false(self) -> None:
        client = _mock_client()
        assert _gateway(client).profile.supports_images is False
