"""SQLAlchemy implementation of ConversationSummaryRepository."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import SummaryTier
from app.domain.memory.summaries import ConversationSummary
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.conversation import ConversationSummaryModel
from app.infrastructure.database.repository import ScopedRepository


class SqlConversationSummaryRepository(ScopedRepository):
    """Reads and writes ConversationSummary rows."""

    def __init__(self, scope: ScopeContext, session: AsyncSession) -> None:
        super().__init__(scope, session)

    async def save(self, scope: ScopeContext, summary: ConversationSummary) -> None:
        self._require_scope(scope)
        row = ConversationSummaryModel(
            id=summary.id,
            user_id=summary.user_id,
            knowledge_base_id=summary.knowledge_base_id,
            conversation_id=summary.conversation_id,
            tier=summary.tier.value,
            text=summary.text,
            message_count=summary.message_count,
            embedding=summary.embedding,
            created_at=summary.created_at,
        )
        self._session.add(row)

    async def save_embedding(
        self,
        scope: ScopeContext,
        summary_id: UUID,
        embedding: Sequence[float],
    ) -> None:
        """Store the dense vector for a summary that already exists."""
        self._require_scope(scope)
        stmt = (
            update(ConversationSummaryModel)
            .where(
                ConversationSummaryModel.id == summary_id,
                self._scope_filter(ConversationSummaryModel),
            )
            .values(embedding=list(embedding))
        )
        await self._session.execute(stmt)

    async def dense_search(
        self,
        scope: ScopeContext,
        query_embedding: Sequence[float],
        *,
        limit: int,
    ) -> Sequence[tuple[ConversationSummary, float]]:
        """Cosine-distance nearest-neighbour search over embedded episode summaries."""
        self._require_scope(scope)
        distance_col = ConversationSummaryModel.embedding.cosine_distance(
            list(query_embedding)
        )
        stmt = (
            select(ConversationSummaryModel, distance_col.label("distance"))
            .where(
                self._scope_filter(ConversationSummaryModel),
                ConversationSummaryModel.embedding.isnot(None),
            )
            .order_by(distance_col)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(_to_entity(row[0]), float(row[1])) for row in rows]

    async def list_by_conversation(
        self,
        scope: ScopeContext,
        conversation_id: UUID,
        *,
        tier: SummaryTier = SummaryTier.EPISODE,
        limit: int = 10,
    ) -> Sequence[ConversationSummary]:
        """Return summaries for one conversation, newest first."""
        self._require_scope(scope)
        stmt = (
            select(ConversationSummaryModel)
            .where(
                self._scope_filter(ConversationSummaryModel),
                ConversationSummaryModel.conversation_id == conversation_id,
                ConversationSummaryModel.tier == tier.value,
            )
            .order_by(ConversationSummaryModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]


def _to_entity(row: ConversationSummaryModel) -> ConversationSummary:
    return ConversationSummary(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        conversation_id=row.conversation_id,
        tier=SummaryTier(row.tier),
        text=row.text,
        message_count=row.message_count,
        created_at=row.created_at,
        embedding=row.embedding,
    )
