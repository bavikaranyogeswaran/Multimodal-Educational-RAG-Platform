"""ConversationSummary entity — immutable snapshot of a block of conversation messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import SummaryTier


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """An immutable episode-level summary of a conversation message block.

    Written by CompactMemoryUseCase and embedded asynchronously by the worker.
    The embedding field is None until the embed step runs.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    conversation_id: UUID
    tier: SummaryTier
    text: str
    message_count: int
    created_at: datetime
    embedding: list[float] | None = None
