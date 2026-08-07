"""Provider-neutral model request and response.

The seven-slot prompt structure is an intermediate representation that the context builder
assembles and the prompt normalizer maps to a provider-specific payload. Neither side of
that boundary knows what the other looks like; the slots are what they agree on. This keeps
provider clients swappable without touching any caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import MessageRole, ModelTask
from app.domain.errors import InvariantViolationError
from app.domain.values import UntrustedText


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One turn of conversation history in provider-neutral form."""

    role: MessageRole
    content: UntrustedText

    def __post_init__(self) -> None:
        if self.content.is_blank():
            raise InvariantViolationError("ConversationTurn content must not be blank")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A provider-neutral inference request in the seven-slot prompt structure.

    Every slot is always present; empty tuples represent absent context, not missing fields.
    This makes the structure uniform and avoids conditional logic in the normalizer.

    Slot ordering (as assembled by the context builder):
      1. system_preamble  — base identity and persistent behaviour rules
      2. safety_rules     — CRITICAL-level constraints applied before any task logic
      3. task_instructions — what this specific invocation requires
      4. memory_context   — verified facts about the student, sourced from the memory store
      5. evidence         — retrieved document passages; kept UntrustedText through this layer
      6. conversation_history — prior turns; user content stays UntrustedText
      7. query            — the rewritten, normalised form of the current question
    """

    model_task: ModelTask
    system_preamble: str
    safety_rules: tuple[str, ...]
    task_instructions: str
    memory_context: tuple[str, ...]
    evidence: tuple[UntrustedText, ...]
    conversation_history: tuple[ConversationTurn, ...]
    query: str
    max_tokens: int | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not self.system_preamble.strip():
            raise InvariantViolationError("ModelRequest.system_preamble must not be blank")
        if not self.task_instructions.strip():
            raise InvariantViolationError("ModelRequest.task_instructions must not be blank")
        if not self.query.strip():
            raise InvariantViolationError("ModelRequest.query must not be blank")
        for rule in self.safety_rules:
            if not rule.strip():
                raise InvariantViolationError("every entry in safety_rules must not be blank")
        for fact in self.memory_context:
            if not fact.strip():
                raise InvariantViolationError("every entry in memory_context must not be blank")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise InvariantViolationError(
                f"ModelRequest.max_tokens must be >= 1, got {self.max_tokens}"
            )
        if self.temperature is not None and not (0.0 <= self.temperature <= 2.0):
            raise InvariantViolationError(
                f"ModelRequest.temperature must be in [0.0, 2.0], got {self.temperature}"
            )

    @property
    def has_evidence(self) -> bool:
        return len(self.evidence) > 0

    @property
    def has_memory(self) -> bool:
        return len(self.memory_context) > 0


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """A provider-neutral response from a model invocation."""

    model_task: ModelTask
    model_id: str
    content: UntrustedText
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise InvariantViolationError("ModelResponse.model_id must not be blank")
        if self.content.is_blank():
            raise InvariantViolationError("ModelResponse.content must not be blank")
        if self.prompt_tokens < 0:
            raise InvariantViolationError(
                f"ModelResponse.prompt_tokens must be >= 0, got {self.prompt_tokens}"
            )
        if self.completion_tokens < 0:
            raise InvariantViolationError(
                f"ModelResponse.completion_tokens must be >= 0, got {self.completion_tokens}"
            )
        if self.latency_ms is not None and self.latency_ms < 0:
            raise InvariantViolationError(
                f"ModelResponse.latency_ms must be >= 0, got {self.latency_ms}"
            )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
