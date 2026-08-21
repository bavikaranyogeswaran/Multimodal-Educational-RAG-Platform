"""Model gateway façade — routes inference requests to the appropriate provider.

The façade is the only implementation of ModelGatewayPort visible to the application
layer. It holds an ordered list of provider adapters and selects the first one whose
profile declares support for the requested task. Provider order is preference order:
when two providers both handle a task, the earlier one in the list wins.

Privacy enforcement and fallback are not part of this step — those are separate
concerns added in steps 8.2 and 8.3. The façade's routing logic is already the right
home for them when they land.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from app.domain.enums import ModelTask
from app.domain.errors import DataBoundaryViolationError, UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import (
    ModelProfile,
    MultimodalCapability,
    TextGenerationCapability,
    TokenStream,
)


class ModelGatewayFacade:
    """Routes model inference requests to the first capable provider.

    Providers are evaluated in registration order. The first provider whose
    profile declares support for the requested task handles the call. Multimodal
    requests are routed to the first provider with `supports_images=True`.
    """

    def __init__(
        self,
        providers: Sequence[TextGenerationCapability | MultimodalCapability],
    ) -> None:
        if not providers:
            raise ValueError("ModelGatewayFacade requires at least one provider")
        self._providers = list(providers)

    def _provider_for(
        self, task: ModelTask
    ) -> TextGenerationCapability | MultimodalCapability:
        for provider in self._providers:
            if provider.profile.supports_task(task):
                return provider
        raise UnsupportedCapabilityError("no configured provider", task.value)

    def _enforce_privacy(
        self,
        request: ModelRequest,
        provider: TextGenerationCapability | MultimodalCapability,
    ) -> None:
        if request.privacy_sensitive and not provider.profile.can_accept_private_content():
            raise DataBoundaryViolationError(
                provider.profile.provider,
                provider.profile.data_boundary.value,
            )

    def profile_for(self, task: ModelTask) -> ModelProfile:
        return self._provider_for(task).profile

    async def generate(self, request: ModelRequest) -> ModelResponse:
        provider = self._provider_for(request.model_task)
        self._enforce_privacy(request, provider)
        return await provider.generate(request)

    def generate_stream(self, request: ModelRequest) -> TokenStream:
        provider = self._provider_for(request.model_task)
        self._enforce_privacy(request, provider)
        return provider.generate_stream(request)

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        for provider in self._providers:
            if provider.profile.supports_images and provider.profile.supports_task(
                ModelTask.VISUAL_QUESTION
            ):
                self._enforce_privacy(request, provider)
                return await cast(MultimodalCapability, provider).generate_with_image(
                    request, image
                )
        raise UnsupportedCapabilityError("no configured provider", "image input")
