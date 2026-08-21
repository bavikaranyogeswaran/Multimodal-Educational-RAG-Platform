"""Model gateway façade — routes inference requests to the appropriate provider.

The façade is the only implementation of ModelGatewayPort visible to the application
layer. It holds an ordered list of provider adapters and, for each request, tries them
in preference order. The first capable provider handles the call; if it fails with a
retryable error, the next capable provider in the list is tried. A non-retryable error
or a privacy violation propagates immediately — there is no silent fallback for either.

Streaming does not participate in the fallback chain: a TokenStream's errors surface
to the caller during iteration, after tokens may already have been delivered, so there
is no safe point at which to switch providers.

When a session_factory is supplied at construction, one model_invocations row is written
per completed call (text and image generation only — streaming is excluded). A write
failure is caught and logged; it never surfaces to the caller.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import ModelTask
from app.domain.errors import DataBoundaryViolationError, ProviderError, UnsupportedCapabilityError
from app.domain.models.entities import ModelRequest, ModelResponse
from app.domain.ports.model_gateway import (
    ModelProfile,
    MultimodalCapability,
    TextGenerationCapability,
    TokenStream,
)
from app.infrastructure.observability.invocation_log import write_model_invocation

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
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ModelGatewayFacade requires at least one provider")
        self._providers = list(providers)
        self._session_factory = session_factory

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

    async def _record_invocation(
        self,
        response: ModelResponse,
        provider: TextGenerationCapability | MultimodalCapability,
        used_fallback: bool,
    ) -> None:
        if self._session_factory is None:
            return
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await write_model_invocation(
                        session=session,
                        model_id=response.model_id,
                        task=response.model_task.value,
                        provider=provider.profile.provider,
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        latency_ms=response.latency_ms,
                        used_fallback=used_fallback,
                    )
        except Exception as exc:
            _log.warning("gateway.invocation_write_failed", error=str(exc))

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
        for index, provider in enumerate(candidates):
            self._enforce_privacy(request, provider)
            try:
                result = await provider.generate(request)
                await self._record_invocation(result, provider, used_fallback=(index > 0))
                return result
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
        for index, provider in enumerate(candidates):
            self._enforce_privacy(request, provider)
            try:
                result = await cast(MultimodalCapability, provider).generate_with_image(
                    request, image
                )
                await self._record_invocation(result, provider, used_fallback=(index > 0))
                return result
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
