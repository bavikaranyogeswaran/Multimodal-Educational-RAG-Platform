"""SQLAlchemy implementation of MemoryRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.conversation import MemoryFactModel
from app.infrastructure.database.repository import ScopedRepository


class SqlMemoryRepository(ScopedRepository):
    """Reads and writes MemoryFact aggregates via SQLAlchemy."""

    async def get(self, scope: ScopeContext, fact_id: UUID) -> MemoryFact | None:
        self._require_scope(scope)
        stmt = (
            select(MemoryFactModel)
            .where(
                MemoryFactModel.id == fact_id,
                self._scope_filter(MemoryFactModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def save(self, scope: ScopeContext, fact: MemoryFact) -> None:
        self._require_scope(scope)
        await self._session.merge(_to_model(fact))

    async def save_batch(self, scope: ScopeContext, facts: Sequence[MemoryFact]) -> None:
        self._require_scope(scope)
        for fact in facts:
            await self._session.merge(_to_model(fact))

    async def list_active(self, scope: ScopeContext) -> Sequence[MemoryFact]:
        self._require_scope(scope)
        stmt = (
            select(MemoryFactModel)
            .where(
                self._scope_filter(MemoryFactModel),
                MemoryFactModel.status == MemoryStatus.ACTIVE.value,
            )
            .order_by(MemoryFactModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def list_all(self, scope: ScopeContext) -> Sequence[MemoryFact]:
        self._require_scope(scope)
        stmt = (
            select(MemoryFactModel)
            .where(self._scope_filter(MemoryFactModel))
            .order_by(MemoryFactModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _utc_opt(dt: datetime | None) -> datetime | None:
    return None if dt is None else _utc(dt)


def _to_entity(row: MemoryFactModel) -> MemoryFact:
    return MemoryFact(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        memory_type=MemoryType(row.memory_type),
        content=row.content,
        provenance=MemoryProvenance(row.provenance),
        status=MemoryStatus(row.status),
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        valid_from=_utc(row.valid_from),
        valid_until=_utc_opt(row.valid_until),
        superseded_by=row.superseded_by,
    )


def _to_model(fact: MemoryFact) -> MemoryFactModel:
    return MemoryFactModel(
        id=fact.id,
        user_id=fact.user_id,
        knowledge_base_id=fact.knowledge_base_id,
        memory_type=fact.memory_type.value,
        content=fact.content,
        provenance=int(fact.provenance),
        status=fact.status.value,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
        valid_from=fact.valid_from,
        valid_until=fact.valid_until,
        superseded_by=fact.superseded_by,
    )
