"""Ollama model gateway — text generation via the /api/chat endpoint.

Satisfies ModelGatewayPort for a locally-running Ollama server. Both
non-streaming (generate) and token-streaming (generate_stream) are supported.
Image inference is not yet implemented (generate_with_image raises
UnsupportedCapabilityError).
"""

from __future__ import annotations

import json as _json
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import httpx

from app.domain.enums import DataBoundary, MessageRole, ModelTask
from app.domain.errors import ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import GenerationUsage, ModelRequest, ModelResponse
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


def _build_messages(request: ModelRequest) -> list[dict[str, str]]:
    """Map the twelve-slot ModelRequest to an Ollama chat messages array, in slot order.

    The system message combines every purely structural slot — identity, safety rules, the
    task, this turn's requirements, the Knowledge Base state — into one authoritative
    block, because Ollama's chat API has no notion of a slot boundary within a single role
    and these are framing the model reads once, not content it is being handed. Each
    requirement occupies its own line, carrying the name a reply can refer to it by and how
    strongly it binds, so what the model receives is a list it can answer point by point
    rather than a paragraph it has to take as a whole. Memory,
    the conversation summary, evidence, the schema and the checklist are turn content
    instead, and each arrives as its own acknowledged exchange — a technique carried over
    from before this request had twelve slots, kept because a fact presented as something
    the model has read and confirmed is attended to differently than the same fact folded
    into an instruction it was never asked to acknowledge.

    The order follows the slots exactly: recent turns before evidence, evidence before the
    question, so a rule stated early is not contradicted by something read later with more
    apparent freshness.
    """
    system_parts = [request.system_preamble, *request.safety_rules, request.task_instructions]
    system_parts.extend(requirement.rendered for requirement in request.mandatory_requirements)
    if request.knowledge_base_state:
        system_parts.append(request.knowledge_base_state)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
    ]

    memory = [*request.pinned_memory, *request.relevant_memory]
    if request.rolling_summary:
        memory.append(request.rolling_summary)
    if memory:
        facts = "\n".join(f"- {fact}" for fact in memory)
        messages.append({"role": "user", "content": f"[Student context]\n{facts}"})
        messages.append({"role": "assistant", "content": "Understood, I have noted the context."})

    for turn in request.conversation_history:
        role = "user" if turn.role is MessageRole.USER else "assistant"
        messages.append({"role": role, "content": turn.content.value})

    if request.evidence:
        passages = "\n\n".join(f"{p.label} {p.text.value}" for p in request.evidence)
        messages.append({"role": "user", "content": f"[Reference material]\n{passages}"})
        messages.append({"role": "assistant", "content": "I have reviewed the material."})

    messages.append({"role": "user", "content": request.query})

    if request.output_schema:
        schema_content = f"[Required output format]\n{request.output_schema}"
        messages.append({"role": "user", "content": schema_content})

    if request.critical_checklist:
        points = "\n".join(f"- {point}" for point in request.critical_checklist)
        messages.append({"role": "user", "content": f"[Before you answer]\n{points}"})

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
        request: ModelRequest,  # noqa: ARG002
        image: bytes,  # noqa: ARG002
    ) -> ModelResponse:
        raise UnsupportedCapabilityError(self._model_id, "image input")
