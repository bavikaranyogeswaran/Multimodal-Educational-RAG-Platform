"""Use case: extract durable facts about the student from a completed conversation turn.

Called after an assistant message is stored. The use case:
  1. Loads the completed assistant message and the user question that preceded it.
  2. Loads all currently active facts to detect key collisions (supersessions).
  3. Calls the extraction port to get candidate MemoryFact instances from the turn.
  4. For each candidate:
     - If an active fact with the same key already exists, create a successor pair
       (retired + new active) and save them atomically via save_batch.
     - Otherwise, save the candidate as a new fact with UNCONFIRMED status.
  5. Returns a count of facts created and superseded.

A message that is not a completed ASSISTANT message, a turn with no preceding user
message in the same conversation, or a port that raises MemoryExtractionError are all
treated as no-ops — the turn is skipped and a zero result is returned. None of these
conditions should fail a request.
"""

from __future__ import annotations

import structlog
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from app.domain.conversations.entities import Message
from app.domain.enums import MessageRole, MessageStatus
from app.domain.errors import MemoryExtractionError
from app.domain.ports.adapters import MemoryExtractionPort
from app.domain.ports.repositories import ConversationRepository, MemoryRepository
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExtractMemoryCommand:
    scope: ScopeContext
    message_id: UUID


@dataclass(frozen=True)
class ExtractMemoryResult:
    created: int
    superseded: int
    # IDs of facts that were written and need an embedding (new facts + successors).
    # Retired SUPERSEDED facts are excluded — they are no longer searched.
    embeddable_ids: tuple[UUID, ...] = field(default_factory=tuple)


class ExtractMemoryUseCase:
    """Extract memory facts from one completed conversation turn.

    The caller is responsible for providing a repository that is already in a
    transaction — writes are not committed here; the caller commits when the
    surrounding unit of work completes.
    """

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        memory_repo: MemoryRepository,
        extractor: MemoryExtractionPort,
    ) -> None:
        self._conv_repo = conversation_repo
        self._memory_repo = memory_repo
        self._extractor = extractor

    async def execute(self, command: ExtractMemoryCommand) -> ExtractMemoryResult:
        scope = command.scope
        now = datetime.now(UTC)

        assistant_msg = await self._conv_repo.get_message(scope, command.message_id)
        if not _is_completed_assistant(assistant_msg):
            _log.debug(
                "extract_memory.skipped",
                reason="message not found or not a completed assistant message",
                message_id=str(command.message_id),
            )
            return ExtractMemoryResult(created=0, superseded=0)

        messages = await self._conv_repo.list_messages(
            scope, assistant_msg.conversation_id
        )
        user_msg = _preceding_user_message(messages, command.message_id)
        if user_msg is None:
            _log.debug(
                "extract_memory.skipped",
                reason="no preceding user message found",
                message_id=str(command.message_id),
            )
            return ExtractMemoryResult(created=0, superseded=0)

        existing = await self._memory_repo.list_active(scope)
        existing_by_key = {f.key: f for f in existing}

        try:
            candidates = await self._extractor.extract(
                scope,
                user_message=user_msg.content.value,
                assistant_message=assistant_msg.content.value,
                source_message_id=command.message_id,
            )
        except MemoryExtractionError:
            _log.warning(
                "extract_memory.extraction_failed",
                message_id=str(command.message_id),
                exc_info=True,
            )
            return ExtractMemoryResult(created=0, superseded=0)

        if not candidates:
            return ExtractMemoryResult(created=0, superseded=0)

        created = 0
        superseded = 0
        to_save = []
        embeddable_ids: list[UUID] = []

        for candidate in candidates:
            existing_fact = existing_by_key.get(candidate.key)
            if existing_fact is not None:
                retired, successor = existing_fact.create_successor(
                    successor_id=candidate.id,
                    value=candidate.value,
                    confidence=candidate.confidence,
                    provenance=candidate.provenance,
                    now=now,
                )
                to_save.extend([retired, successor])
                embeddable_ids.append(successor.id)
                superseded += 1
            else:
                to_save.append(candidate)
                embeddable_ids.append(candidate.id)
                created += 1

        await self._memory_repo.save_batch(scope, to_save)

        _log.info(
            "extract_memory.complete",
            message_id=str(command.message_id),
            created=created,
            superseded=superseded,
        )

        return ExtractMemoryResult(
            created=created,
            superseded=superseded,
            embeddable_ids=tuple(embeddable_ids),
        )


def _is_completed_assistant(msg: Message | None) -> bool:
    return (
        msg is not None
        and msg.role is MessageRole.ASSISTANT
        and msg.status is MessageStatus.COMPLETED
    )


def _preceding_user_message(
    messages: list[Message] | tuple[Message, ...],  # type: ignore[type-arg]
    assistant_message_id: UUID,
) -> Message | None:
    """Return the USER message immediately before the given assistant message.

    list_messages returns most-recent-first; the assistant message comes first,
    the user question that triggered it comes next.
    """
    found_assistant = False
    for msg in messages:
        if not found_assistant:
            if msg.id == assistant_message_id:
                found_assistant = True
            continue
        if msg.role is MessageRole.USER:
            return msg
    return None
