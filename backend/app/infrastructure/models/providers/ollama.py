"""Ollama model gateway — text generation and multimodal inference via /api/chat.

Satisfies ModelGatewayPort for a locally-running Ollama server. Both
non-streaming (generate) and token-streaming (generate_stream) are supported.
Image inference is implemented via Ollama's images field in chat messages;
the image is base64-encoded and attached to the query message.
"""

from __future__ import annotations

import base64 as _base64
import json as _json
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import httpx

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import GenerationUsage, ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile
from app.domain.values import UntrustedText
from app.infrastructure.models.providers.prompt import (
    DEFAULT_PROMPT_PROFILE,
    PromptProfile,
    build_chat_messages,
)

_ALL_TASKS: frozenset[ModelTask] = frozenset(
    {
        ModelTask.QUERY_REWRITE,
        ModelTask.QUERY_EXPANSION,
        ModelTask.ANSWER_GENERATION,
        ModelTask.VISUAL_QUESTION,
        ModelTask.MULTI_HOP_DECOMPOSITION,
        ModelTask.SUMMARIZATION,
        ModelTask.QUIZ_GENERATION,
        ModelTask.MEMORY_EXTRACTION,
        ModelTask.GRAPH_EXTRACTION,
        ModelTask.FAITHFULNESS_CHECK,
        ModelTask.QUERY_CLASSIFICATION,
    }
)


class OllamaTokenStream:
    """Yields the content of each NDJSON line, keeping the counts on the last one.

    Ollama reports `prompt_eval_count`, `eval_count` and `done_reason` only on the final
    line of the stream — the one carrying `done: true` and no content. Iterating token by
    token and discarding everything else drops them, which is why the raw lines are what
    this consumes and plain strings are what it yields.

    `usage` stays `None` until the stream is exhausted. A caller that reads it early gets
    the honest answer: the provider has not said yet.
    """

    def __init__(self, lines: AsyncGenerator[dict[str, Any], None], model_id: str) -> None:
        self._lines = lines
        self._model_id = model_id
        self._usage: GenerationUsage | None = None

    @property
    def usage(self) -> GenerationUsage | None:
        return self._usage

    async def __aiter__(self) -> AsyncIterator[str]:
        async for data in self._lines:
            token: str = data.get("message", {}).get("content", "")
            if token:
                yield token
            if data.get("done"):
                self._usage = GenerationUsage(
                    model_id=self._model_id,
                    prompt_tokens=data.get("prompt_eval_count", 0),
                    completion_tokens=data.get("eval_count", 0),
                    finish_reason=data.get("done_reason"),
                )


class OllamaModelGateway:
    """ModelGatewayPort backed by a locally-running Ollama server.

    Uses /api/chat (non-streaming) for all text generation tasks. The injected
    httpx.AsyncClient is closed by the caller; this class does not own its lifecycle.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        model_id: str,
        *,
        timeout_seconds: int,
        prompt_profile: PromptProfile | None = None,
    ) -> None:
        self._client = http_client
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._prompt_profile = prompt_profile if prompt_profile is not None else DEFAULT_PROMPT_PROFILE
        self._profile = ModelProfile(
            model_key=model_id,
            provider="ollama",
            tasks=_ALL_TASKS,
            data_boundary=DataBoundary.LOCAL,
            # gemma3:4b supports 128 K tokens; callers see the real cap.
            context_tokens=131_072,
            max_output_tokens=8_192,
            supports_images=True,
        )

    @property
    def profile(self) -> ModelProfile:
        return self._profile

    def profile_for(self, task: ModelTask) -> ModelProfile:
        if not self._profile.supports_task(task):
            raise UnsupportedCapabilityError(self._model_id, task.value)
        return self._profile

    async def generate(self, request: ModelRequest) -> ModelResponse:
        messages = build_chat_messages(request, self._prompt_profile)

        options: dict[str, object] = {}
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.temperature is not None:
            options["temperature"] = request.temperature

        payload: dict[str, object] = {
            "model": self._model_id,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        t0 = time.monotonic()
        try:
            resp = await self._client.post("/api/chat", json=payload, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            raise ProviderError("ollama", str(exc), retryable=retryable) from exc
        except httpx.RequestError as exc:
            raise ProviderError("ollama", str(exc), retryable=True) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()

        return ModelResponse(
            model_task=request.model_task,
            model_id=self._model_id,
            content=UntrustedText(data["message"]["content"]),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            finish_reason=data.get("done_reason"),
            latency_ms=latency_ms,
        )

    def generate_stream(self, request: ModelRequest) -> OllamaTokenStream:
        """Stream response tokens, and report what the call cost once they stop.

        Uses /api/chat with stream:true, which returns one NDJSON line per token.
        Errors that occur before or during streaming propagate as ProviderError
        when the caller first advances the iterator.
        """
        return OllamaTokenStream(self._token_lines(request), self._model_id)

    async def _token_lines(self, request: ModelRequest) -> AsyncGenerator[dict[str, Any], None]:
        """The decoded NDJSON lines, including the final one carrying the counts."""
        messages = build_chat_messages(request, self._prompt_profile)

        options: dict[str, object] = {}
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.temperature is not None:
            options["temperature"] = request.temperature

        payload: dict[str, object] = {
            "model": self._model_id,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options

        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload, timeout=self._timeout
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = _json.loads(line)
                    yield data
                    if data.get("done"):
                        break
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            raise ProviderError("ollama", str(exc), retryable=retryable) from exc
        except httpx.RequestError as exc:
            raise ProviderError("ollama", str(exc), retryable=True) from exc

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        """Multimodal inference via Ollama's /api/chat images field.

        The image is base64-encoded and attached to the last user message, which
        is always the query in our prompt structure. Ollama delivers it to the
        vision-capable model alongside the text.
        """
        messages = build_chat_messages(request, self._prompt_profile)
        image_b64 = _base64.b64encode(image).decode("ascii")

        # Attach the image to the last user message (the query). The prompt
        # builder always puts the query there, followed optionally by output
        # schema and checklist messages that do not need the image.
        for i in reversed(range(len(messages))):
            if messages[i]["role"] == "user":
                messages[i] = {**messages[i], "images": [image_b64]}  # type: ignore[dict-item]
                break

        options: dict[str, object] = {}
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.temperature is not None:
            options["temperature"] = request.temperature

        payload: dict[str, object] = {
            "model": self._model_id,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        t0 = time.monotonic()
        try:
            resp = await self._client.post("/api/chat", json=payload, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            raise ProviderError("ollama", str(exc), retryable=retryable) from exc
        except httpx.RequestError as exc:
            raise ProviderError("ollama", str(exc), retryable=True) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()

        return ModelResponse(
            model_task=request.model_task,
            model_id=self._model_id,
            content=UntrustedText(data["message"]["content"]),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            finish_reason=data.get("done_reason"),
            latency_ms=latency_ms,
        )
