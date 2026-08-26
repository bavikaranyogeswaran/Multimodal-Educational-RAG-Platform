"""Domain errors.

The domain raises these; the presentation layer decides what they mean over HTTP. Nothing
here knows about status codes, because a status code is a transport concern and putting one
in the domain is how the transport ends up pinned to it.

One distinction matters more than the others. `NotFoundError` and `ScopeViolationError` are separate
types even though the API answers both with the same response — a resource the caller does
not own must be indistinguishable from one that does not exist, or the API becomes an
oracle for guessing identifiers. Keeping them distinct internally is what allows a scope
violation to be recorded as a security event while a genuine miss is not.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


class DomainError(Exception):
    """Base for every error the domain raises deliberately."""


class AuthenticationError(DomainError):
    """The caller's identity could not be established.

    Raised when a token is missing, malformed, expired or does not resolve to a
    known identity. The presentation layer maps this to HTTP 401.
    """


class InvariantViolationError(DomainError, ValueError):
    """An entity or value object was constructed in a state it must never hold.

    Subclasses `ValueError` so that ordinary construction-time checks read naturally to
    callers who are not thinking about the domain hierarchy.
    """


class IllegalTransitionError(DomainError):
    """A state machine was asked to move somewhere it cannot go."""

    def __init__(self, entity: str, current: str, requested: str) -> None:
        super().__init__(f"{entity} cannot move from {current} to {requested}")
        self.entity = entity
        self.current = current
        self.requested = requested


class NotFoundError(DomainError):
    """A record does not exist within the caller's scope.

    Deliberately does not distinguish "absent" from "belongs to someone else" in its
    message — see the module docstring.
    """

    def __init__(self, entity: str, identifier: Any = None) -> None:
        detail = f"{entity} not found" + (f": {identifier}" if identifier else "")
        super().__init__(detail)
        self.entity = entity
        self.identifier = identifier


class ScopeViolationError(DomainError):
    """An operation attempted to cross a user or Knowledge Base boundary.

    Reaching this means a check that should have happened earlier did not. It is a
    security event, not a routine miss, and carries the identifiers needed to investigate
    without having to reconstruct them from a stack trace.
    """

    def __init__(
        self,
        *,
        expected_user_id: UUID,
        expected_knowledge_base_id: UUID,
        actual_user_id: UUID | None = None,
        actual_knowledge_base_id: UUID | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(detail or "operation crossed a scope boundary")
        self.expected_user_id = expected_user_id
        self.expected_knowledge_base_id = expected_knowledge_base_id
        self.actual_user_id = actual_user_id
        self.actual_knowledge_base_id = actual_knowledge_base_id


class ConflictError(DomainError):
    """The requested change contradicts the current state."""


class UploadValidationError(DomainError):
    """An uploaded file did not pass content or size validation.

    Raised before any persistence or storage write occurs. The presentation
    layer maps this to HTTP 422 so the client receives a structured error
    body rather than a raw 5xx.
    """


class UnsupportedCapabilityError(DomainError):
    """A model was asked for something it does not support.

    Raised before the provider is called, not after it fails: asking a text-only model to
    read an image should be refused by the gateway rather than discovered in a response.
    """

    def __init__(self, model_key: str, capability: str) -> None:
        super().__init__(f"model {model_key!r} does not support {capability}")
        self.model_key = model_key
        self.capability = capability


class DataBoundaryViolationError(DomainError):
    """Private content would have been sent to a provider that may not receive it.

    Always fatal to the request. There is no fallback path, because rerouting to a
    permitted provider would defeat the purpose of having asked.
    """

    def __init__(self, provider: str, boundary: str) -> None:
        super().__init__(
            f"provider {provider!r} has data boundary {boundary!r} and may not receive "
            "private documents, memory or personal identifiers"
        )
        self.provider = provider
        self.boundary = boundary


class ProviderError(DomainError):
    """A model provider failed.

    `retryable` is decided where the failure is understood rather than where it is
    handled. A timeout is worth retrying; a malformed request or an exhausted context
    window is not, and retrying it just spends the budget twice.
    """

    def __init__(self, provider: str, detail: str, *, retryable: bool) -> None:
        super().__init__(f"{provider}: {detail}")
        self.provider = provider
        self.retryable = retryable


class GenerationParseError(DomainError):
    """The model's response did not conform to the required output schema.

    Raised by the parser when the JSON is malformed, a required field is absent or the
    wrong type, or a claim carries no citations. The caller decides whether this is
    repairable or a rejection — that judgement is not made here.
    """


class GraphExtractionError(DomainError):
    """The model's graph extraction output could not be parsed or failed validation.

    Raised by GraphExtractionPort implementations when the JSON is malformed,
    a field is missing or the wrong type, a type string is unrecognised, or a
    provenance invariant would be violated (blank evidence, self-referencing edge,
    unresolved entity name). The BUILD_GRAPH worker catches this to skip the chunk
    and continue with others rather than failing the entire job.
    """


class GenerationRejectedError(DomainError):
    """A generated answer could not be grounded in the retrieved evidence.

    Raised when decide() returns REJECTED on the first attempt, or when a REPAIRABLE
    answer still fails validation after a single repair attempt. The presentation layer
    should treat this as a recoverable failure and return an appropriate message to the
    student rather than a 5xx.

    `abstained` is True when the model correctly determined the material does not cover
    the question (INSUFFICIENT_EVIDENCE), and False when a citation was fabricated or the
    evidence contradicts the claim (REJECTED). The two call for different messages: one
    is about the material, the other is about a quality failure.
    """

    def __init__(self, message: str, *, abstained: bool = False) -> None:
        super().__init__(message)
        self.abstained = abstained
