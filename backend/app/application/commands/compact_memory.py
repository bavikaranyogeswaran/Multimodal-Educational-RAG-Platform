"""Use case: compact a conversation's history into a rolling summary.

Called by the COMPACT_MEMORY background job when the message-count threshold is crossed.
The use case:
  1. Loads the conversation and its full history (most recent first from the repo,
     reversed to chronological order for the summarizer).
  2. Returns early when the count falls below the configured minimum — another job
     may have already compacted, or the conversation is simply too short.
  3. Calls the summarization port with the current turns and any prior summary.
  4. Writes the new summary back to the conversation via with_summary(), committing
     once in the caller's session.

Original messages are never deleted — the summary is additive context, not a
replacement for the canonical history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from app.domain.enums import SummaryTier
from app.domain.memory.summaries import ConversationSummary
from app.domain.ports.adapters import SummarizationPort
from app.domain.ports.repositories import ConversationRepository, ConversationSummaryRepository
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CompactMemoryCommand:
    scope: ScopeContext
    conversation_id: UUID


@dataclass(frozen=True)
class CompactMemoryResult:
    summary_written: bool
    episode_summary_id: UUID | None = None
    episode_summary_text: str | None = None


class CompactMemoryUseCase:
    """Summarize a conversation's history and write the result as a rolling summary.

    The caller is responsible for providing a repository already in a transaction —
    writes are not committed here.
    """

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        summarizer: SummarizationPort,
        *,
        min_messages: int,
        summary_repo: ConversationSummaryRepository | None = None,
    ) -> None:
        self._conv_repo = conversation_repo
        self._summarizer = summarizer
        self._min_messages = min_messages
        self._summary_repo = summary_repo

    async def execute(self, command: CompactMemoryCommand) -> CompactMemoryResult:
        scope = command.scope
        now = datetime.now(UTC)

        conversation = await self._conv_repo.get(scope, command.conversation_id)
        if conversation is None:
            _log.debug(
                "compact_memory.skipped",
                reason="conversation not found",
                conversation_id=str(command.conversation_id),
            )
            return CompactMemoryResult(summary_written=False)

        # list_history returns most recent first; use a generous limit so the
        # summarizer sees the full picture, not just the last page.
        messages = await self._conv_repo.list_history(
            scope, command.conversation_id, limit=500
        )
        if len(messages) < self._min_messages:
            _log.debug(
                "compact_memory.skipped",
                reason="below threshold",
                message_count=len(messages),
                min_messages=self._min_messages,
                conversation_id=str(command.conversation_id),
            )
            return CompactMemoryResult(summary_written=False)

        # Reverse so the summarizer receives turns oldest-first.
        turns = [msg.content.value for msg in reversed(messages)]

        summary = await self._summarizer.summarize(
            scope,
            turns=turns,
            previous_summary=conversation.rolling_summary,
        )

        updated = conversation.with_summary(summary, now=now)
        await self._conv_repo.save(scope, updated)

        episode_summary_id: UUID | None = None
        if self._summary_repo is not None:
            episode = ConversationSummary(
                id=uuid4(),
                user_id=scope.user_id,
                knowledge_base_id=scope.knowledge_base_id,
                conversation_id=command.conversation_id,
                tier=SummaryTier.EPISODE,
                text=summary,
                message_count=len(messages),
                created_at=now,
            )
            await self._summary_repo.save(scope, episode)
            episode_summary_id = episode.id

        _log.info(
            "compact_memory.complete",
            conversation_id=str(command.conversation_id),
            message_count=len(messages),
            episode_written=episode_summary_id is not None,
        )
        return CompactMemoryResult(
            summary_written=True,
            episode_summary_id=episode_summary_id,
            episode_summary_text=summary if episode_summary_id is not None else None,
        )
