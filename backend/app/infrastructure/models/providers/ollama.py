"""Ollama model gateway — text generation via the /api/chat endpoint.

Satisfies ModelGatewayPort for a locally-running Ollama server. Both
non-streaming (generate) and token-streaming (generate_stream) are supported.
Image inference is not yet implemented (generate_with_image raises
UnsupportedCapabilityError).
"""

from __future__ import annotations

import json as _json
import time
from collections.abc import AsyncGenerator

import httpx

from app.domain.enums import DataBoundary, MessageRole, ModelTask
from app.domain.errors import ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile
from app.domain.values import UntrustedText

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


def _build_messages(request: ModelRequest) -> list[dict[str, str]]:
    """Map the seven-slot ModelRequest to an Ollama chat messages array.

    The system message combines the three structural slots (preamble, safety rules,
    and task instructions) so they arrive as a single authoritative context block.
    Memory and evidence are injected as acknowledged user turns before conversation
    history and the final query.
    """
    system_parts = [request.system_preamble]
    system_parts.extend(request.safety_rules)
    system_parts.append(request.task_instructions)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
    ]

    if request.memory_context:
        facts = "\n".join(f"- {fact}" for fact in request.memory_context)
        messages.append({"role": "user", "content": f"[Student context]\n{facts}"})
        messages.append({"role": "assistant", "content": "Understood, I have noted the context."})

    if request.evidence:
        passages = "\n\n".join(ev.value for ev in request.evidence)
        messages.append({"role": "user", "content": f"[Reference material]\n{passages}"})
        messages.append({"role": "assistant", "content": "I have reviewed the material."})

    for turn in request.conversation_history:
        role = "user" if turn.role is MessageRole.USER else "assistant"
        messages.append({"role": role, "content": turn.content.value})

    messages.append({"role": "user", "content": request.query})

    return messages


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
    ) -> None:
        self._client = http_client
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._profile = ModelProfile(
            model_key=model_id,
            provider="ollama",
            tasks=_ALL_TEXT_TASKS,
            data_boundary=DataBoundary.LOCAL,
            # gemma3:4b supports 128 K tokens; callers see the real cap.
            context_tokens=131_072,
            max_output_tokens=8_192,
            supports_images=False,
        )

    @property
    def profile(self) -> ModelProfile:
        return self._profile

    def profile_for(self, task: ModelTask) -> ModelProfile:
        if not self._profile.supports_task(task):
            raise UnsupportedCapabilityError(self._model_id, task.value)
        return self._profile

    async def generate(self, request: ModelRequest) -> ModelResponse:
        messages = _build_messages(request)

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
            resp = await self._client.post(
                "/api/chat", json=payload, timeout=self._timeout
            )
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

    async def generate_stream(
        self, request: ModelRequest
    ) -> AsyncGenerator[str, None]:
        """Yield individual token strings as they arrive from the Ollama server.

        Uses /api/chat with stream:true, which returns one NDJSON line per token.
        Errors that occur before or during streaming propagate as ProviderError
        when the caller first advances the iterator.
        """
        messages = _build_messages(request)

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
                    token: str = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code >= 500
            raise ProviderError("ollama", str(exc), retryable=retryable) from exc
        except httpx.RequestError as exc:
            raise ProviderError("ollama", str(exc), retryable=True) from exc

    async def generate_with_image(
        self, request: ModelRequest, image: bytes  # noqa: ARG002
    ) -> ModelResponse:
        raise UnsupportedCapabilityError(self._model_id, "image input")
