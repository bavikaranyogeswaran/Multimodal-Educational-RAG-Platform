"""OpenAI-compatible model gateway — text generation via /v1/chat/completions.

Speaks the OpenAI Chat Completions API, which is also implemented by vLLM,
llama.cpp server, Mistral AI, and OpenAI itself. The base URL is injected at
construction time so the same class serves both local inference servers and
third-party cloud endpoints.

Image inference is not supported by this adapter; use the Ollama adapter for
multimodal models.
"""

from __future__ import annotations

import json as _json
import time
from collections.abc import AsyncGenerator, AsyncIterator

import httpx

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import GenerationUsage, ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile
from app.domain.values import UntrustedText
from app.infrastructure.models.providers.prompt import build_chat_messages

_ALL_TEXT_TASKS: frozenset[ModelTask] = frozenset(
    {
        ModelTask.QUERY_REWRITE,
        ModelTask.QUERY_EXPANSION,
        ModelTask.ANSWER_GENERATION,
        ModelTask.MULTI_HOP_DECOMPOSITION,
        ModelTask.SUMMARIZATION,
        ModelTask.QUIZ_GENERATION,
        ModelTask.MEMORY_EXTRACTION,
        ModelTask.GRAPH_EXTRACTION,
        ModelTask.FAITHFULNESS_CHECK,
    }
)

_PROVIDER_NAME = "openai_compat"


class OpenAICompatTokenStream:
    """Parses OpenAI-style SSE and yields content tokens.

    Each SSE line is `data: <json>` with a `choices[0].delta.content` field,
    or the terminal `data: [DONE]`. Usage arrives on the last data chunk when
    the request includes `stream_options: {"include_usage": true}`.

    `usage` stays `None` until the stream is fully exhausted.
    """

    def __init__(
        self,
        lines: AsyncGenerator[str, None],
        model_id: str,
    ) -> None:
        self._lines = lines
        self._model_id = model_id
        self._usage: GenerationUsage | None = None

    @property
    def usage(self) -> GenerationUsage | None:
        return self._usage

    async def __aiter__(self) -> AsyncIterator[str]:
        finish_reason: str | None = None
        prompt_tokens = 0
        completion_tokens = 0

        async for raw_line in self._lines:
            line = raw_line.strip()
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload == "[DONE]":
                break

            try:
                chunk = _json.loads(payload)
            except _json.JSONDecodeError:
                continue

            usage_data = chunk.get("usage")
            if usage_data:
                prompt_tokens = usage_data.get("prompt_tokens", 0)
                completion_tokens = usage_data.get("completion_tokens", 0)

            choices = chunk.get("choices") or []
            if not choices:
                continue

            choice = choices[0]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

            token: str = choice.get("delta", {}).get("content") or ""
            if token:
                yield token

        self._usage = GenerationUsage(
            model_id=self._model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )


class OpenAICompatibleGateway:
    """ModelGatewayPort backed by any OpenAI-compatible /v1/chat/completions endpoint.

    The injected httpx.AsyncClient carries the base URL and is closed by the
    caller; this class does not own its lifecycle. An optional bearer token is
    forwarded on every request if provided.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        model_id: str,
        *,
        timeout_seconds: int,
        data_boundary: DataBoundary = DataBoundary.THIRD_PARTY,
        api_key: str = "",
        context_tokens: int = 128_000,
        max_output_tokens: int = 4_096,
    ) -> None:
        self._client = http_client
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._api_key = api_key
        self._profile = ModelProfile(
            model_key=model_id,
            provider=_PROVIDER_NAME,
            tasks=_ALL_TEXT_TASKS,
            data_boundary=data_boundary,
            context_tokens=context_tokens,
            max_output_tokens=max_output_tokens,
            supports_images=False,
        )

    @property
    def profile(self) -> ModelProfile:
        return self._profile

    def profile_for(self, task: ModelTask) -> ModelProfile:
        if not self._profile.supports_task(task):
            raise UnsupportedCapabilityError(self._model_id, task.value)
        return self._profile

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _base_payload(self, request: ModelRequest, *, stream: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self._model_id,
            "messages": build_chat_messages(request),
            "stream": stream,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        return payload

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload = self._base_payload(request, stream=False)

        t0 = time.monotonic()
        try:
            resp = await self._client.post(
                "/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            raise ProviderError(_PROVIDER_NAME, str(exc), retryable=retryable) from exc
        except httpx.RequestError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc), retryable=True) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()

        usage = data.get("usage", {})
        choices = data.get("choices", [{}])
        finish_reason: str | None = choices[0].get("finish_reason") if choices else None
        content: str = choices[0].get("message", {}).get("content", "") if choices else ""

        return ModelResponse(
            model_task=request.model_task,
            model_id=self._model_id,
            content=UntrustedText(content),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )

    def generate_stream(self, request: ModelRequest) -> OpenAICompatTokenStream:
        """Stream response tokens via SSE, and report usage once they stop."""
        return OpenAICompatTokenStream(self._sse_lines(request), self._model_id)

    async def _sse_lines(self, request: ModelRequest) -> AsyncGenerator[str, None]:
        """The raw SSE text lines from the streaming endpoint."""
        payload = self._base_payload(request, stream=True)
        payload["stream_options"] = {"include_usage": True}

        try:
            async with self._client.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    yield line
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            raise ProviderError(_PROVIDER_NAME, str(exc), retryable=retryable) from exc
        except httpx.RequestError as exc:
            raise ProviderError(_PROVIDER_NAME, str(exc), retryable=True) from exc

    async def generate_with_image(
        self,
        request: ModelRequest,  # noqa: ARG002
        image: bytes,  # noqa: ARG002
    ) -> ModelResponse:
        raise UnsupportedCapabilityError(self._model_id, "image input")
