"""Provider-neutral model request and response.

The twelve-slot prompt structure is an intermediate representation that the context builder
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
class LabeledPassage:
    """One retrieved passage exactly as it will be shown to the model: its citation label
    and its text.

    A plain string label rather than the retrieval package's `EvidenceLabel`, so a
    provider-neutral request does not import a type from the package that produced it — by
    the time a passage reaches here, all that matters is what to print. Carrying the label
    at all is the point: without it the model has no way to say which passage it is citing,
    and the citations Phase 11 must validate would not exist to check.
    """

    label: str
    text: UntrustedText

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise InvariantViolationError("LabeledPassage.label must not be blank")
        if self.text.is_blank():
            raise InvariantViolationError("LabeledPassage.text must not be blank")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """A provider-neutral inference request in the twelve-slot prompt structure.

    Every slot is always present; empty tuples and `None` represent absent context, not
    missing fields. This makes the structure uniform and avoids conditional logic in the
    normalizer — a provider adapter renders whatever is there and skips whatever is not,
    rather than asking whether a slot exists at all.

    Slot ordering (as assembled by the context builder):
       1. system_preamble, safety_rules — identity and the constraints that apply before
          any task logic; safety rules are never dropped and never outranked
       2. task_instructions        — what this specific invocation requires
       3. mandatory_requirements   — this turn's specific constraints, plain for now; given
          priority and stable identifiers once structured instruction handling is built
       4. knowledge_base_state     — what Knowledge Base this conversation is scoped to
       5. pinned_memory            — durable facts the student has fixed in place
       6. relevant_memory          — facts the memory store judged relevant to this turn
       7. rolling_summary          — a compacted account of the conversation so far
       8. conversation_history     — recent turns verbatim; user content stays UntrustedText
       9. evidence                 — retrieved passages, each carrying the label the model
          cites it by; kept UntrustedText through this layer
      10. query                    — the rewritten, normalised form of the current question
      11. output_schema            — the shape the answer must take, once one is defined
      12. critical_checklist       — final reinforcement, read last and so read freshest
    """

    model_task: ModelTask
    system_preamble: str
    safety_rules: tuple[str, ...]
    task_instructions: str
    query: str
    mandatory_requirements: tuple[str, ...] = ()
    knowledge_base_state: str | None = None
    pinned_memory: tuple[str, ...] = ()
    relevant_memory: tuple[str, ...] = ()
    rolling_summary: str | None = None
    conversation_history: tuple[ConversationTurn, ...] = ()
    evidence: tuple[LabeledPassage, ...] = ()
    output_schema: str | None = None
    critical_checklist: tuple[str, ...] = ()
    max_tokens: int | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not self.system_preamble.strip():
            raise InvariantViolationError("ModelRequest.system_preamble must not be blank")
        if not self.task_instructions.strip():
            raise InvariantViolationError("ModelRequest.task_instructions must not be blank")
        if not self.query.strip():
            raise InvariantViolationError("ModelRequest.query must not be blank")
        self._require_no_blank_entries()
        self._require_no_blank_optional_slots()
        if self.max_tokens is not None and self.max_tokens < 1:
            raise InvariantViolationError(
                f"ModelRequest.max_tokens must be >= 1, got {self.max_tokens}"
            )
        if self.temperature is not None and not (0.0 <= self.temperature <= 2.0):
            raise InvariantViolationError(
                f"ModelRequest.temperature must be in [0.0, 2.0], got {self.temperature}"
            )

    def _require_no_blank_entries(self) -> None:
        """A blank entry in a list slot is a bug upstream, not an empty item to render."""
        for field_name, entries in (
            ("safety_rules", self.safety_rules),
            ("mandatory_requirements", self.mandatory_requirements),
            ("pinned_memory", self.pinned_memory),
            ("relevant_memory", self.relevant_memory),
            ("critical_checklist", self.critical_checklist),
        ):
            if any(not entry.strip() for entry in entries):
                raise InvariantViolationError(f"every entry in {field_name} must not be blank")

    def _require_no_blank_optional_slots(self) -> None:
        for field_name, value in (
            ("knowledge_base_state", self.knowledge_base_state),
            ("rolling_summary", self.rolling_summary),
            ("output_schema", self.output_schema),
        ):
            if value is not None and not value.strip():
                raise InvariantViolationError(
                    f"ModelRequest.{field_name} must not be blank when present"
                )

    @property
    def has_evidence(self) -> bool:
        return len(self.evidence) > 0

    @property
    def has_memory(self) -> bool:
        return bool(self.pinned_memory or self.relevant_memory)


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
