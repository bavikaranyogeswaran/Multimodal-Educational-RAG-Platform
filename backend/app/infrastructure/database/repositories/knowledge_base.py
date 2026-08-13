"""SQLAlchemy implementation of KnowledgeBaseRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.domain.enums import ExplanationLevel
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.repository import ScopedRepository


class SqlKnowledgeBaseRepository(ScopedRepository):
    """Reads and writes KnowledgeBase aggregates via SQLAlchemy."""

    async def get(self, scope: ScopeContext) -> KnowledgeBase | None:
        self._require_scope(scope)
        stmt = (
            select(KnowledgeBaseModel)
            .where(
                KnowledgeBaseModel.id == self._scope.knowledge_base_id,
                self._user_filter(KnowledgeBaseModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def save(self, scope: ScopeContext, kb: KnowledgeBase) -> None:
        self._require_scope(scope)
        await self._session.merge(_to_model(kb))

    async def delete(self, scope: ScopeContext) -> None:
        self._require_scope(scope)
        stmt = sa_delete(KnowledgeBaseModel).where(
            KnowledgeBaseModel.id == self._scope.knowledge_base_id,
            self._user_filter(KnowledgeBaseModel),
        )
        await self._session.execute(stmt)

    async def list_for_user(self, user_id: UUID) -> Sequence[KnowledgeBase]:
        stmt = (
            select(KnowledgeBaseModel)
            .where(KnowledgeBaseModel.user_id == user_id)
            .order_by(KnowledgeBaseModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _to_entity(row: KnowledgeBaseModel) -> KnowledgeBase:
    return KnowledgeBase(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        description=row.description,
        subject=row.subject,
        learning_goal=row.learning_goal,
        preferred_language=row.preferred_language,
        explanation_level=ExplanationLevel(row.explanation_level),
        exam_date=row.exam_date,
        graph_enabled=row.graph_enabled,
        active_index_version=row.active_index_version,
        active_graph_version=row.active_graph_version,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _to_model(kb: KnowledgeBase) -> KnowledgeBaseModel:
    return KnowledgeBaseModel(
        id=kb.id,
        user_id=kb.user_id,
        name=kb.name,
        description=kb.description,
        subject=kb.subject,
        learning_goal=kb.learning_goal,
        preferred_language=kb.preferred_language,
        explanation_level=kb.explanation_level.value,
        exam_date=kb.exam_date,
        graph_enabled=kb.graph_enabled,
        active_index_version=kb.active_index_version,
        active_graph_version=kb.active_graph_version,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )
