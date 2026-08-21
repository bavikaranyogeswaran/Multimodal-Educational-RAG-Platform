"""Gemini provider stub — interface-only until credentials are configured.

Declares a profile so the gateway can list this provider, but every call to
generate or generate_stream raises NotImplementedError. Wire in when a
GEMINI_API_KEY is available and the native SDK adapter is built.
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


class GeminiGateway:
    """Placeholder for the Gemini 1.5 / 2.0 provider.

    Raises NotImplementedError on all inference calls. The profile is real so
    the facade can include this adapter in its candidate list once credentials
    are available.
    """

    def __init__(self, model_id: str = "gemini-2.0-flash") -> None:
        self._model_id = model_id
        self._profile = ModelProfile(
            model_key=model_id,
            provider="gemini",
            tasks=_ALL_TEXT_TASKS,
            data_boundary=DataBoundary.THIRD_PARTY,
            context_tokens=1_000_000,
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

    async def generate(self, request: ModelRequest) -> ModelResponse:  # noqa: ARG002
        raise NotImplementedError(
            "GeminiGateway: credentials not configured — add GEMINI_API_KEY and implement the native SDK adapter"
        )

    def generate_stream(self, request: ModelRequest) -> None:  # type: ignore[return]  # noqa: ARG002
        raise NotImplementedError(
            "GeminiGateway: credentials not configured — add GEMINI_API_KEY and implement the native SDK adapter"
        )

    async def generate_with_image(
        self,
        request: ModelRequest,  # noqa: ARG002
        image: bytes,  # noqa: ARG002
    ) -> ModelResponse:
        raise NotImplementedError(
            "GeminiGateway: credentials not configured — add GEMINI_API_KEY and implement the native SDK adapter"
        )
