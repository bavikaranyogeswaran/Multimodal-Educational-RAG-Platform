"""Model gateway port — the application-facing inference interface.

Defines the capability metadata type, the two provider-level capability
protocols (text generation and multimodal), and the gateway port the
application layer calls to route inference requests.

EmbeddingPort and RerankerPort are pure-computation adapters defined in
adapters.py; they carry no private content and require no privacy pre-flight,
so the gateway does not route them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from app.domain.enums import DataBoundary, ModelTask
from app.domain.errors import InvariantViolationError
from app.domain.models.entities import GenerationUsage, ModelRequest, ModelResponse


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Immutable description of what a single model provider can do.

    Carried by the gateway so callers can inspect the privacy constraint before
    assembling a prompt — avoiding wasted token serialisation for a request the
    gateway would refuse.
    """

    model_key: str
    provider: str
    tasks: frozenset[ModelTask]
    data_boundary: DataBoundary
    context_tokens: int
    max_output_tokens: int
    supports_images: bool = False

    def __post_init__(self) -> None:
        if not self.model_key.strip():
            raise InvariantViolationError("ModelProfile.model_key must not be blank")
        if not self.provider.strip():
            raise InvariantViolationError("ModelProfile.provider must not be blank")
        if not self.tasks:
            raise InvariantViolationError("ModelProfile must declare at least one supported task")
        if self.context_tokens < 1:
            raise InvariantViolationError(
                f"ModelProfile.context_tokens must be >= 1, got {self.context_tokens}"
            )
        if self.max_output_tokens < 1:
            raise InvariantViolationError(
                f"ModelProfile.max_output_tokens must be >= 1, got {self.max_output_tokens}"
            )
        if ModelTask.VISUAL_QUESTION in self.tasks and not self.supports_images:
            raise InvariantViolationError(
                "a profile that includes VISUAL_QUESTION must have supports_images=True"
            )

    def supports_task(self, task: ModelTask) -> bool:
        return task in self.tasks

    def can_accept_private_content(self) -> bool:
        return self.data_boundary.accepts_private_content


# ---------------------------------------------------------------------------
# Provider-level capability protocols
# ---------------------------------------------------------------------------


class TextGenerationCapability(Protocol):
    """Provider-level text generation, streaming and non-streaming.

    Implementations do not check the data boundary — the gateway does that
    before selecting a provider. A provider that receives a request has already
    been cleared to handle its content.
    """

    @property
    def profile(self) -> ModelProfile: ...

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    def generate_stream(self, request: ModelRequest) -> TokenStream: ...


class MultimodalCapability(TextGenerationCapability, Protocol):
    """Provider-level text + image inference.

    Extends TextGenerationCapability: a multimodal provider handles all text
    tasks plus image input. The gateway routes VISUAL_QUESTION tasks to
    `generate_with_image` and all others to `generate`.
    """

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse: ...


class TokenStream(Protocol):
    """Response tokens as they arrive, and what the call cost once they have stopped.

    Iterating is the point; `usage` is what the non-streaming path gets for free in its
    `ModelResponse` and the streaming path would otherwise throw away. It is `None` until
    the stream is exhausted, because the counts do not exist until the provider has
    finished producing — and stays `None` for a provider that never reports them, which
    is why the caller must treat it as absent rather than as zero.
    """

    def __aiter__(self) -> AsyncIterator[str]: ...

    @property
    def usage(self) -> GenerationUsage | None: ...


# ---------------------------------------------------------------------------
# Application-level gateway port
# ---------------------------------------------------------------------------


class ModelGatewayPort(Protocol):
    """Routing and privacy enforcement layer for model inference.

    The gateway selects a provider for every request based on the task and
    privacy requirements. If the request carries private content (student
    documents, memory facts, identifiers) and the only capable provider has
    data_boundary=THIRD_PARTY, it raises DataBoundaryViolationError rather
    than rerouting silently.

    `profile_for` is synchronous: the registry is an in-memory structure, not
    IO. It is exposed so callers can inspect the selected provider's boundary
    before assembling a prompt.
    """

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Route to the best capable provider and return the response.

        Raises:
            DataBoundaryViolationError: private content sent to a THIRD_PARTY provider.
            UnsupportedCapabilityError: no configured provider supports the task.
        """
        ...

    async def generate_with_image(
        self,
        request: ModelRequest,
        image: bytes,
    ) -> ModelResponse:
        """Multimodal inference. Same routing and privacy pre-flight as `generate`.

        Raises:
            UnsupportedCapabilityError: no configured provider supports VISUAL_QUESTION.
            DataBoundaryViolationError: same conditions as `generate`.
        """
        ...

    def generate_stream(self, request: ModelRequest) -> TokenStream:
        """Yield response tokens as they arrive, one delta string at a time.

        The iterator must be consumed within a single request context.
        Errors (provider failures, timeouts) propagate as ProviderError at the
        point the caller advances the iterator.

        Once exhausted, the stream reports its `usage`. Callers that only need the text
        may iterate and ignore it; callers recording what the turn cost read it after
        the loop, never during, because it is not known until the provider is done.
        """
        ...

    def profile_for(self, task: ModelTask) -> ModelProfile:
        """The model profile that would be selected for the given task.

        Raises:
            UnsupportedCapabilityError: no provider is configured for the task.
        """
        ...
