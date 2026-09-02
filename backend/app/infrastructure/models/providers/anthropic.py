"""Anthropic provider stub — interface-only until credentials are configured.

Declares a profile so the gateway can list this provider, but every call to
generate or generate_stream raises NotImplementedError. Wire in when an
ANTHROPIC_API_KEY is available and the native SDK adapter is built.
"""

from __future__ import annotations

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import ModelProfile

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


class AnthropicGateway:
    """Placeholder for the Claude (Anthropic) provider.

    Raises NotImplementedError on all inference calls. The profile is real so
    the facade can include this adapter in its candidate list once credentials
    are available.
    """

    def __init__(self, model_id: str = "claude-sonnet-5") -> None:
        self._model_id = model_id
        self._profile = ModelProfile(
            model_key=model_id,
            provider="anthropic",
            tasks=_ALL_TEXT_TASKS,
            data_boundary=DataBoundary.THIRD_PARTY,
            context_tokens=200_000,
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
        raise NotImplementedError(
            "AnthropicGateway: credentials not configured — add ANTHROPIC_API_KEY and implement the native SDK adapter"
        )

    def generate_stream(self, request: ModelRequest) -> None:
        raise NotImplementedError(
            "AnthropicGateway: credentials not configured — add ANTHROPIC_API_KEY and implement the native SDK adapter"
        )

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        raise NotImplementedError(
            "AnthropicGateway: credentials not configured — add ANTHROPIC_API_KEY and implement the native SDK adapter"
        )
