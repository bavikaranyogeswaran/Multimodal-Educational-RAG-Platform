"""SQLAlchemy implementation of MemoryRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import column, func, select, update
from sqlalchemy.sql.elements import ColumnElement

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.conversation import MemoryFactModel
from app.infrastructure.database.repository import ScopedRepository

_TS_CONFIG = "english"


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

    async def get_active_by_key(self, scope: ScopeContext, key: str) -> MemoryFact | None:
        self._require_scope(scope)
        stmt = (
            select(MemoryFactModel)
            .where(
                MemoryFactModel.key == key,
                self._scope_filter(MemoryFactModel),
                MemoryFactModel.status == MemoryStatus.ACTIVE.value,
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

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

    async def update_embedding(
        self, scope: ScopeContext, fact_id: UUID, embedding: Sequence[float]
    ) -> None:
        """Store the dense vector for a fact without touching any other field."""
        self._require_scope(scope)
        stmt = (
            update(MemoryFactModel)
            .where(
                MemoryFactModel.id == fact_id,
                self._scope_filter(MemoryFactModel),
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
    ) -> Sequence[tuple[MemoryFact, float]]:
        """Cosine-distance nearest-neighbour search over ACTIVE fact embeddings."""
        self._require_scope(scope)
        distance_col = MemoryFactModel.embedding.cosine_distance(list(query_embedding))
        stmt = (
            select(MemoryFactModel, distance_col.label("distance"))
            .where(
                self._scope_filter(MemoryFactModel),
                MemoryFactModel.status == MemoryStatus.ACTIVE.value,
                MemoryFactModel.embedding.isnot(None),
            )
            .order_by(distance_col)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(_to_entity(row[0]), float(row[1])) for row in rows]

    async def keyword_search(
        self,
        scope: ScopeContext,
        query_text: str,
        *,
        limit: int,
    ) -> Sequence[tuple[MemoryFact, float]]:
        """Full-text search over the trigger-maintained tsv column of ACTIVE facts."""
        self._require_scope(scope)
        # tsv is not declared on MemoryFactModel because it is PostgreSQL-specific and
        # managed by a database trigger, not application code. column() references it
        # by name without requiring an ORM mapping.
        tsv_col: ColumnElement[Any] = column("tsv")
        ts_query = func.plainto_tsquery(_TS_CONFIG, query_text)
        score_col = func.ts_rank_cd(tsv_col, ts_query)
        stmt = (
            select(MemoryFactModel, score_col.label("rank_score"))
            .where(
                self._scope_filter(MemoryFactModel),
                MemoryFactModel.status == MemoryStatus.ACTIVE.value,
                tsv_col.isnot(None),
                tsv_col.op("@@")(ts_query),
            )
            .order_by(score_col.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(_to_entity(row[0]), float(row[1])) for row in rows]

    async def list_expiring(
        self, scope: ScopeContext, *, before: datetime
    ) -> Sequence[MemoryFact]:
        """ACTIVE facts whose expires_at is set and falls on or before `before`."""
        self._require_scope(scope)
        stmt = (
            select(MemoryFactModel)
            .where(
                self._scope_filter(MemoryFactModel),
                MemoryFactModel.status == MemoryStatus.ACTIVE.value,
                MemoryFactModel.expires_at.isnot(None),
                MemoryFactModel.expires_at <= before,
            )
            .order_by(MemoryFactModel.expires_at)
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
        key=row.key,
        value=row.value or {},
        confidence=row.confidence,
        source_message_id=row.source_message_id,
        last_confirmed_at=_utc_opt(row.last_confirmed_at),
        expires_at=_utc_opt(row.expires_at),
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
        key=fact.key,
        value=fact.value,
        confidence=fact.confidence,
        source_message_id=fact.source_message_id,
        last_confirmed_at=fact.last_confirmed_at,
        expires_at=fact.expires_at,
        provenance=int(fact.provenance),
        status=fact.status.value,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
        valid_from=fact.valid_from,
        valid_until=fact.valid_until,
        superseded_by=fact.superseded_by,
    )
