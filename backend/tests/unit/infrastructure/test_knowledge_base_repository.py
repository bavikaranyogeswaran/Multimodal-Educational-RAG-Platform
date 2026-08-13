"""Tests for SqlKnowledgeBaseRepository against an in-memory SQLite database.

Covers CRUD operations, scope isolation, and result ordering. Entity constructors
run on each round-trip, so invariant violations (nil ids, timezone-naive datetimes,
etc.) would surface here even without explicit assertions.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ScopeViolationError
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.knowledge_base import SqlKnowledgeBaseRepository


def _make_scope(
    *,
    user_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
) -> ScopeContext:
    return ScopeContext(
        user_id=user_id or uuid.uuid4(),
        knowledge_base_id=kb_id or uuid.uuid4(),
    )


def _make_kb(scope: ScopeContext, *, name: str = "Test KB", age_seconds: int = 0) -> KnowledgeBase:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return KnowledgeBase(
        id=scope.knowledge_base_id,
        user_id=scope.user_id,
        name=name,
        created_at=ts,
        updated_at=ts,
    )


def _repo(scope: ScopeContext, session: AsyncSession) -> SqlKnowledgeBaseRepository:
    return SqlKnowledgeBaseRepository(scope=scope, session=session)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_matching_kb(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        kb = _make_kb(scope)
        await _repo(scope, sqlite_session).save(scope, kb)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope)

        assert result is not None
        assert result.id == kb.id
        assert result.name == kb.name
        assert result.user_id == kb.user_id

    async def test_returns_none_when_kb_id_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get(scope)
        assert result is None

    async def test_user_isolation_blocks_cross_user_read(
        self, sqlite_session: AsyncSession
    ) -> None:
        kb_id = uuid.uuid4()
        scope_a = _make_scope(kb_id=kb_id)
        scope_b = _make_scope(kb_id=kb_id)

        await _repo(scope_a, sqlite_session).save(scope_a, _make_kb(scope_a))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope_b, sqlite_session).get(scope_b)
        assert result is None


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    async def test_insert_then_get(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        kb = _make_kb(scope)
        await _repo(scope, sqlite_session).save(scope, kb)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope)
        assert result is not None

    async def test_update_existing_kb(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        kb = _make_kb(scope, name="Original")
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, kb)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        updated = replace(kb, name="Updated", updated_at=datetime.now(UTC))
        await repo.save(scope, updated)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get(scope)
        assert result is not None
        assert result.name == "Updated"

    async def test_optional_fields_round_trip(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        ts = datetime.now(UTC)
        kb = KnowledgeBase(
            id=scope.knowledge_base_id,
            user_id=scope.user_id,
            name="Full KB",
            description="Study material",
            subject="Math",
            learning_goal="Pass the exam",
            graph_enabled=True,
            created_at=ts,
            updated_at=ts,
        )
        await _repo(scope, sqlite_session).save(scope, kb)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope)
        assert result is not None
        assert result.description == "Study material"
        assert result.subject == "Math"
        assert result.graph_enabled is True


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_removes_kb(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        kb = _make_kb(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, kb)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        await repo.delete(scope)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo.get(scope) is None

    async def test_delete_is_scoped_by_user(self, sqlite_session: AsyncSession) -> None:
        kb_id = uuid.uuid4()
        scope_a = _make_scope(kb_id=kb_id)
        scope_b = _make_scope(kb_id=kb_id)

        await _repo(scope_a, sqlite_session).save(scope_a, _make_kb(scope_a))
        await sqlite_session.flush()

        await _repo(scope_b, sqlite_session).delete(scope_b)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await _repo(scope_a, sqlite_session).get(scope_a) is not None


# ---------------------------------------------------------------------------
# list_for_user
# ---------------------------------------------------------------------------


class TestListForUser:
    async def test_returns_all_kbs_for_user(self, sqlite_session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        scope1 = _make_scope(user_id=user_id)
        scope2 = _make_scope(user_id=user_id)
        now = datetime.now(UTC)

        kb1 = KnowledgeBase(
            id=scope1.knowledge_base_id, user_id=user_id, name="KB-1",
            created_at=now - timedelta(seconds=60), updated_at=now - timedelta(seconds=60),
        )
        kb2 = KnowledgeBase(
            id=scope2.knowledge_base_id, user_id=user_id, name="KB-2",
            created_at=now, updated_at=now,
        )

        await _repo(scope1, sqlite_session).save(scope1, kb1)
        await _repo(scope2, sqlite_session).save(scope2, kb2)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope1, sqlite_session).list_for_user(user_id)
        assert len(results) == 2

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        scope_old = _make_scope(user_id=user_id)
        scope_new = _make_scope(user_id=user_id)

        older = KnowledgeBase(
            id=scope_old.knowledge_base_id, user_id=user_id, name="Older",
            created_at=now - timedelta(seconds=120), updated_at=now - timedelta(seconds=120),
        )
        newer = KnowledgeBase(
            id=scope_new.knowledge_base_id, user_id=user_id, name="Newer",
            created_at=now, updated_at=now,
        )

        await _repo(scope_old, sqlite_session).save(scope_old, older)
        await _repo(scope_new, sqlite_session).save(scope_new, newer)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_old, sqlite_session).list_for_user(user_id)
        assert results[0].name == "Newer"
        assert results[1].name == "Older"

    async def test_user_isolation(self, sqlite_session: AsyncSession) -> None:
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        scope_a = _make_scope(user_id=user_a)
        scope_b = _make_scope(user_id=user_b)
        now = datetime.now(UTC)

        await _repo(scope_a, sqlite_session).save(
            scope_a,
            KnowledgeBase(id=scope_a.knowledge_base_id, user_id=user_a, name="A",
                          created_at=now, updated_at=now),
        )
        await _repo(scope_b, sqlite_session).save(
            scope_b,
            KnowledgeBase(id=scope_b.knowledge_base_id, user_id=user_b, name="B",
                          created_at=now, updated_at=now),
        )
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list_for_user(user_a)
        assert len(results) == 1
        assert results[0].user_id == user_a

    async def test_empty_list_when_no_kbs(self, sqlite_session: AsyncSession) -> None:
        user_id = uuid.uuid4()
        scope = _make_scope(user_id=user_id)
        results = await _repo(scope, sqlite_session).list_for_user(user_id)
        assert results == [] or list(results) == []


# ---------------------------------------------------------------------------
# Scope guard — a call carrying someone else's scope never reaches the session
#
# list_for_user is absent here on purpose: it takes a user id rather than a
# ScopeContext, because listing is what establishes the scope in the first place.
# ---------------------------------------------------------------------------


class TestKnowledgeBaseScopeGuard:
    async def test_get_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.get(_make_scope())

        session.execute.assert_not_called()

    async def test_save_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)

        with pytest.raises(ScopeViolationError):
            await repo.save(_make_scope(), _make_kb(scope))

        session.merge.assert_not_called()

    async def test_delete_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.delete(_make_scope())

        session.execute.assert_not_called()

    async def test_same_user_different_kb_is_still_rejected(self) -> None:
        # Two Knowledge Bases owned by one user are still two boundaries.
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)

        with pytest.raises(ScopeViolationError):
            await repo.get(_make_scope(user_id=scope.user_id))

        session.execute.assert_not_called()
