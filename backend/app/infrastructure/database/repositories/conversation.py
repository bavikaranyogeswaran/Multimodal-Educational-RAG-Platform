"""SQLAlchemy implementation of ConversationRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.domain.conversations.entities import Conversation, Message
from app.domain.enums import MessageRole, MessageStatus
from app.domain.retrieval.entities import Evidence
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.models.conversation import (
    ConversationModel,
    ConversationRetrievalChunkModel,
    MessageModel,
)
from app.infrastructure.database.repository import ScopedRepository


class SqlConversationRepository(ScopedRepository):
    """Reads and writes Conversation and Message aggregates via SQLAlchemy."""

    async def get(self, scope: ScopeContext, conversation_id: UUID) -> Conversation | None:
        self._require_scope(scope)
        stmt = (
            select(ConversationModel)
            .where(
                ConversationModel.id == conversation_id,
                self._scope_filter(ConversationModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _conv_to_entity(row) if row else None

    async def save(self, scope: ScopeContext, conversation: Conversation) -> None:
        self._require_scope(scope)
        await self._session.merge(_conv_to_model(conversation))

    async def list(self, scope: ScopeContext) -> Sequence[Conversation]:
        self._require_scope(scope)
        stmt = (
            select(ConversationModel)
            .where(self._scope_filter(ConversationModel))
            .order_by(ConversationModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_conv_to_entity(row) for row in rows]

    async def delete(self, scope: ScopeContext, conversation_id: UUID) -> None:
        self._require_scope(scope)
        stmt = sa_delete(ConversationModel).where(
            ConversationModel.id == conversation_id,
            self._scope_filter(ConversationModel),
        )
        await self._session.execute(stmt)

    async def get_message(self, scope: ScopeContext, message_id: UUID) -> Message | None:
        self._require_scope(scope)
        stmt = (
            select(MessageModel)
            .where(
                MessageModel.id == message_id,
                self._scope_filter(MessageModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _msg_to_entity(row) if row else None

    async def save_message(self, scope: ScopeContext, message: Message) -> None:
        self._require_scope(scope)
        await self._session.merge(_msg_to_model(message))

    async def list_messages(
        self, scope: ScopeContext, conversation_id: UUID, *, limit: int = 50
    ) -> Sequence[Message]:
        self._require_scope(scope)
        stmt = (
            select(MessageModel)
            .where(
                MessageModel.conversation_id == conversation_id,
                self._scope_filter(MessageModel),
            )
            .order_by(MessageModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_msg_to_entity(row) for row in rows]

    async def save_retrieval_chunks(
        self, scope: ScopeContext, message_id: UUID, evidence: Sequence[Evidence]
    ) -> None:
        self._require_scope(scope)
        if not evidence:
            return
        now = datetime.now(UTC)
        for item in evidence:
            # merge rather than add, so re-running generation for the same message
            # overwrites its previous record instead of colliding on the composite key.
            await self._session.merge(
                ConversationRetrievalChunkModel(
                    message_id=message_id,
                    chunk_id=item.chunk.id,
                    rank=item.rank,
                    score=_persisted_score(item),
                    created_at=now,
                )
            )


def _persisted_score(item: Evidence) -> float:
    """The score that explains the stored rank, taking the last stage that produced one.

    Reranking decides the final order when it runs, so its score is the one that makes
    the rank intelligible. Fusion score stands in when the pipeline returned before
    reranking. Zero is the last resort: the column is not nullable because a row
    recording position without any score behind it is a record nobody can interpret.
    """
    if item.rerank_score is not None:
        return item.rerank_score
    if item.fusion_score is not None:
        return item.fusion_score
    return 0.0


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _conv_to_entity(row: ConversationModel) -> Conversation:
    return Conversation(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        title=row.title,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        active_document_id=row.active_document_id,
        active_page_number=row.active_page_number,
        active_figure_id=row.active_figure_id,
        active_table_id=row.active_table_id,
    )


def _conv_to_model(conv: Conversation) -> ConversationModel:
    return ConversationModel(
        id=conv.id,
        user_id=conv.user_id,
        knowledge_base_id=conv.knowledge_base_id,
        title=conv.title,
        active_document_id=conv.active_document_id,
        active_page_number=conv.active_page_number,
        active_figure_id=conv.active_figure_id,
        active_table_id=conv.active_table_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _msg_to_entity(row: MessageModel) -> Message:
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        role=MessageRole(row.role),
        status=MessageStatus(row.status),
        content=UntrustedText(row.content),
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        rewritten_query=row.rewritten_query,
        model_id=row.model_id,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        finish_reason=row.finish_reason,
    )


def _msg_to_model(msg: Message) -> MessageModel:
    return MessageModel(
        id=msg.id,
        conversation_id=msg.conversation_id,
        user_id=msg.user_id,
        knowledge_base_id=msg.knowledge_base_id,
        role=msg.role.value,
        status=msg.status.value,
        content=msg.content.value,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
        rewritten_query=msg.rewritten_query,
        model_id=msg.model_id,
        prompt_tokens=msg.prompt_tokens,
        completion_tokens=msg.completion_tokens,
        finish_reason=msg.finish_reason,
    )
