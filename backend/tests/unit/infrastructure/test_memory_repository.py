"""Tests for SqlMemoryRepository against an in-memory SQLite database.

Covers get, save, save_batch, list_active, list_all, and scope isolation.
The memory_facts table uses only standard SQL types (no ARRAY/JSONB), so SQLite
works without mocking. The self-referential superseded_by FK is supported by SQLite
at DDL time and is not enforced at runtime (FK enforcement is off by default).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.errors import ScopeViolationError
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.memory import SqlMemoryRepository

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_scope(
    *,
    user_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
) -> ScopeContext:
    return ScopeContext(
        user_id=user_id or uuid.uuid4(),
        knowledge_base_id=kb_id or uuid.uuid4(),
    )


def _make_fact(
    scope: ScopeContext,
    *,
    key: str = "preference",
    value: dict | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    age_seconds: int = 0,
) -> MemoryFact:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return MemoryFact(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        memory_type=MemoryType.PREFERENCE,
        key=key,
        value=value if value is not None else {"text": "Student prefers concise answers."},
        confidence=0.9,
        provenance=MemoryProvenance.USER_STATEMENT,
        status=status,
        created_at=ts,
        updated_at=ts,
        valid_from=ts,
    )


def _repo(scope: ScopeContext, session: AsyncSession) -> SqlMemoryRepository:
    return SqlMemoryRepository(scope=scope, session=session)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_matching_fact(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        fact = _make_fact(scope)
        await _repo(scope, sqlite_session).save(scope, fact)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope, fact.id)

        assert result is not None
        assert result.id == fact.id
        assert result.key == fact.key
        assert result.value == fact.value
        assert result.confidence == fact.confidence
        assert result.provenance == MemoryProvenance.USER_STATEMENT

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get(scope, uuid.uuid4())
        assert result is None


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    async def test_insert_then_get(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        fact = _make_fact(scope)
        await _repo(scope, sqlite_session).save(scope, fact)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope, fact.id)
        assert result is not None

    async def test_update_existing(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        fact = _make_fact(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, fact)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        disputed = fact.mark_disputed(now=datetime.now(UTC))
        await repo.save(scope, disputed)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get(scope, fact.id)
        assert result is not None
        assert result.status == MemoryStatus.DISPUTED


# ---------------------------------------------------------------------------
# save_batch
# ---------------------------------------------------------------------------


class TestSaveBatch:
    async def test_saves_multiple_facts(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        facts = [_make_fact(scope, key=f"fact_{i}") for i in range(4)]
        await _repo(scope, sqlite_session).save_batch(scope, facts)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope, sqlite_session).list_all(scope)
        assert len(results) == 4

    async def test_empty_batch_is_no_op(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        session_mock = AsyncMock()
        await _repo(scope, session_mock).save_batch(scope, [])
        session_mock.merge.assert_not_called()


# ---------------------------------------------------------------------------
# list_active
# ---------------------------------------------------------------------------


class TestListActive:
    async def test_returns_only_active_facts(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        repo = _repo(scope, sqlite_session)
        active = _make_fact(scope, status=MemoryStatus.ACTIVE)
        disputed = _make_fact(scope, status=MemoryStatus.DISPUTED)
        await repo.save(scope, active)
        await repo.save(scope, disputed)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_active(scope)
        assert len(results) == 1
        assert results[0].id == active.id

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, _make_fact(scope, key="older_key", age_seconds=60))
        await repo.save(scope, _make_fact(scope, key="newer_key", age_seconds=0))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_active(scope)
        assert results[0].key == "newer_key"

    async def test_user_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _repo(scope_a, sqlite_session).save(scope_a, _make_fact(scope_a))
        await _repo(scope_b, sqlite_session).save(scope_b, _make_fact(scope_b))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list_active(scope_a)
        assert len(results) == 1
        assert results[0].user_id == scope_a.user_id


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestListAll:
    async def test_returns_facts_of_all_statuses(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, _make_fact(scope, status=MemoryStatus.ACTIVE))
        await repo.save(scope, _make_fact(scope, status=MemoryStatus.DISPUTED))
        await repo.save(scope, _make_fact(scope, status=MemoryStatus.UNCONFIRMED))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_all(scope)
        assert len(results) == 3

    async def test_user_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _repo(scope_a, sqlite_session).save(scope_a, _make_fact(scope_a))
        await _repo(scope_b, sqlite_session).save(scope_b, _make_fact(scope_b))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list_all(scope_a)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Scope guard — a call carrying someone else's scope never reaches the session
# ---------------------------------------------------------------------------


class TestMemoryScopeGuard:
    async def test_get_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.get(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save(_make_scope(), _make_fact(scope))
        session.merge.assert_not_called()

    async def test_save_batch_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_batch(_make_scope(), [_make_fact(scope)])
        session.merge.assert_not_called()

    async def test_list_active_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_active(_make_scope())
        session.execute.assert_not_called()

    async def test_list_all_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_all(_make_scope())
        session.execute.assert_not_called()
