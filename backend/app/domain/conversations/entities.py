"""Conversation and message entities.

A conversation tracks which document, page, and visual element the student is looking at.
That context drives routing: a question asked while a table is selected routes differently
from the same words asked without one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.domain.enums import MessageRole, MessageStatus
from app.domain.errors import IllegalTransitionError, InvariantViolationError
from app.domain.invariants import (
    require_non_blank,
    require_ordered,
    require_positive,
    require_timezone_aware,
)
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText


@dataclass(frozen=True, slots=True)
class Conversation:
    """A study session within one Knowledge Base.

    Active context — which document, page, figure or table the student has open — is stored
    on the conversation because it shapes retrieval without the student having to repeat it
    in every message.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    active_document_id: UUID | None = None
    active_page_number: int | None = None
    active_figure_id: UUID | None = None
    active_table_id: UUID | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.title, "title")
        require_timezone_aware(self.created_at, "created_at")
        require_timezone_aware(self.updated_at, "updated_at")
        require_ordered(
            self.created_at,
            self.updated_at,
            earlier_field="created_at",
            later_field="updated_at",
        )
        if self.active_page_number is not None:
            require_positive(self.active_page_number, "active_page_number")
            if self.active_document_id is None:
                raise InvariantViolationError(
                    "active_page_number requires active_document_id to be set"
                )
        if self.active_figure_id is not None and self.active_document_id is None:
            raise InvariantViolationError(
                "active_figure_id requires active_document_id to be set"
            )
        if self.active_table_id is not None and self.active_document_id is None:
            raise InvariantViolationError(
                "active_table_id requires active_document_id to be set"
            )
        if self.active_figure_id is not None and self.active_table_id is not None:
            raise InvariantViolationError(
                "figure and table selections are mutually exclusive"
            )

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    def renamed(self, title: str, *, now: datetime) -> Conversation:
        return replace(self, title=title, updated_at=now)

    def focus_document(self, document_id: UUID, *, now: datetime) -> Conversation:
        """Switch to a different document, resetting page and visual selection."""
        return replace(
            self,
            active_document_id=document_id,
            active_page_number=None,
            active_figure_id=None,
            active_table_id=None,
            updated_at=now,
        )

    def focus_page(self, page_number: int, *, now: datetime) -> Conversation:
        """Navigate to a page within the active document, clearing any visual selection."""
        return replace(
            self,
            active_page_number=page_number,
            active_figure_id=None,
            active_table_id=None,
            updated_at=now,
        )

    def focus_figure(self, figure_id: UUID, *, now: datetime) -> Conversation:
        """Select a figure, replacing any prior table selection."""
        return replace(
            self,
            active_figure_id=figure_id,
            active_table_id=None,
            updated_at=now,
        )

    def focus_table(self, table_id: UUID, *, now: datetime) -> Conversation:
        """Select a table, replacing any prior figure selection."""
        return replace(
            self,
            active_table_id=table_id,
            active_figure_id=None,
            updated_at=now,
        )

    def clear_selection(self, *, now: datetime) -> Conversation:
        """Remove page and visual context while keeping the active document."""
        return replace(
            self,
            active_page_number=None,
            active_figure_id=None,
            active_table_id=None,
            updated_at=now,
        )


@dataclass(frozen=True, slots=True)
class Message:
    """One turn in a conversation — either a student question or an assistant answer.

    User messages are stored the moment they arrive. The status then tracks the lifecycle
    of the system's response: generation in progress, completed, or failed.

    Model metadata (which model answered, how many tokens it used) is recorded on assistant
    messages after generation. Query rewriting records its output on user messages.

    Content is UntrustedText for both roles. User input may carry injection attempts;
    assistant output may carry injected content absorbed from documents. Neither should be
    interpolated into a subsequent prompt without explicit access via `.value`.
    """

    id: UUID
    conversation_id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    role: MessageRole
    status: MessageStatus
    content: UntrustedText
    created_at: datetime
    updated_at: datetime
    rewritten_query: str | None = None
    model_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    #: Names the prompt template that produced this answer. Absent on user messages,
    #: which are not produced by a prompt, and on answers written before it was recorded.
    prompt_version: str | None = None

    def __post_init__(self) -> None:
        if self.content.is_blank():
            raise InvariantViolationError("content must not be blank")
        require_timezone_aware(self.created_at, "created_at")
        require_timezone_aware(self.updated_at, "updated_at")
        if self.rewritten_query is not None:
            if not self.rewritten_query.strip():
                raise InvariantViolationError("rewritten_query must not be blank")
            if self.role is not MessageRole.USER:
                raise InvariantViolationError(
                    "rewritten_query applies only to user messages"
                )
        _validate_model_metadata(self)

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    @property
    def has_model_metadata(self) -> bool:
        return self.model_id is not None

    def mark_processing(self, *, now: datetime) -> Message:
        self._transition(MessageStatus.PROCESSING)
        return replace(self, status=MessageStatus.PROCESSING, updated_at=now)

    def mark_completed(self, *, now: datetime) -> Message:
        self._transition(MessageStatus.COMPLETED)
        return replace(self, status=MessageStatus.COMPLETED, updated_at=now)

    def mark_failed(self, *, now: datetime) -> Message:
        self._transition(MessageStatus.FAILED)
        return replace(self, status=MessageStatus.FAILED, updated_at=now)

    def with_rewritten_query(self, query: str, *, now: datetime) -> Message:
        if self.role is not MessageRole.USER:
            raise InvariantViolationError(
                "query rewriting applies only to user messages"
            )
        if not query.strip():
            raise InvariantViolationError("rewritten_query must not be blank")
        return replace(self, rewritten_query=query, updated_at=now)

    def with_model_metadata(
        self,
        *,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        finish_reason: str | None = None,
        now: datetime,
    ) -> Message:
        if self.role is not MessageRole.ASSISTANT:
            raise InvariantViolationError(
                "model metadata applies only to assistant messages"
            )
        return replace(
            self,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
            updated_at=now,
        )

    def _transition(self, target: MessageStatus) -> None:
        if not self.status.can_transition_to(target):
            raise IllegalTransitionError("Message", self.status, target)


def _validate_model_metadata(msg: Message) -> None:
    has_id = msg.model_id is not None
    has_prompt = msg.prompt_tokens is not None
    has_completion = msg.completion_tokens is not None
    if not (has_id == has_prompt == has_completion):
        raise InvariantViolationError(
            "model_id, prompt_tokens and completion_tokens must be set together"
        )
    if has_id and msg.role is not MessageRole.ASSISTANT:
        raise InvariantViolationError(
            "model metadata applies only to assistant messages"
        )
    if msg.prompt_version is not None:
        if not msg.prompt_version.strip():
            raise InvariantViolationError("prompt_version must not be blank")
        # Deliberately not tied to model_id: a turn can be refused before the provider
        # reports anything, and the prompt that was sent is still worth naming.
        if msg.role is not MessageRole.ASSISTANT:
            raise InvariantViolationError(
                "prompt_version applies only to assistant messages"
            )
