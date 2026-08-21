"""Model gateway façade — routes inference requests to the appropriate provider.

The façade is the only implementation of ModelGatewayPort visible to the application
layer. It holds an ordered list of provider adapters and, for each request, tries them
in preference order. The first capable provider handles the call; if it fails with a
retryable error, the next capable provider in the list is tried. A non-retryable error
or a privacy violation propagates immediately — there is no silent fallback for either.

Streaming does not participate in the fallback chain: a TokenStream's errors surface
to the caller during iteration, after tokens may already have been delivered, so there
is no safe point at which to switch providers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import structlog

from app.domain.enums import ModelTask
from app.domain.errors import DataBoundaryViolationError, ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import (
    ModelProfile,
    MultimodalCapability,
    TextGenerationCapability,
    TokenStream,
)

_log = structlog.get_logger(__name__)


class ModelGatewayFacade:
    """Routes model inference requests to the first capable provider.

    Providers are evaluated in registration order. On a retryable ProviderError
    the next capable provider is tried; a non-retryable error or a privacy
    violation propagates immediately. If every capable provider fails, the last
    ProviderError is re-raised.
    """

    def __init__(
        self,
        providers: Sequence[TextGenerationCapability | MultimodalCapability],
    ) -> None:
        if not providers:
            raise ValueError("ModelGatewayFacade requires at least one provider")
        self._providers = list(providers)

    def _capable_providers(
        self, task: ModelTask
    ) -> list[TextGenerationCapability | MultimodalCapability]:
        return [p for p in self._providers if p.profile.supports_task(task)]

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
        candidates = self._capable_providers(task)
        if not candidates:
            raise UnsupportedCapabilityError("no configured provider", task.value)
        return candidates[0].profile

    async def generate(self, request: ModelRequest) -> ModelResponse:
        candidates = self._capable_providers(request.model_task)
        if not candidates:
            raise UnsupportedCapabilityError("no configured provider", request.model_task.value)

        last_error: ProviderError | None = None
        for provider in candidates:
            self._enforce_privacy(request, provider)
            try:
                return await provider.generate(request)
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                _log.warning(
                    "gateway.provider_fallback",
                    task=request.model_task.value,
                    failed_provider=exc.provider,
                    error=str(exc),
                )
                last_error = exc

        raise last_error  # type: ignore[misc]

    def generate_stream(self, request: ModelRequest) -> TokenStream:
        candidates = self._capable_providers(request.model_task)
        if not candidates:
            raise UnsupportedCapabilityError("no configured provider", request.model_task.value)
        provider = candidates[0]
        self._enforce_privacy(request, provider)
        return provider.generate_stream(request)

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        candidates = [
            p
            for p in self._providers
            if p.profile.supports_images and p.profile.supports_task(ModelTask.VISUAL_QUESTION)
        ]
        if not candidates:
            raise UnsupportedCapabilityError("no configured provider", "image input")

        last_error: ProviderError | None = None
        for provider in candidates:
            self._enforce_privacy(request, provider)
            try:
                return await cast(MultimodalCapability, provider).generate_with_image(
                    request, image
                )
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                _log.warning(
                    "gateway.provider_fallback",
                    task=request.model_task.value,
                    failed_provider=exc.provider,
                    error=str(exc),
                )
                last_error = exc

        raise last_error  # type: ignore[misc]
