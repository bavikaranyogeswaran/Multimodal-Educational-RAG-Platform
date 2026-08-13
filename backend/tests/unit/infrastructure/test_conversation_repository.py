"""Tests for SqlConversationRepository against an in-memory SQLite database.

Covers CRUD for both Conversation and Message aggregates, scope isolation,
result ordering, and the limit parameter on list_messages. The SQLite session
includes the knowledge_bases, conversations, and messages tables. A KB row is
inserted before each test that saves a conversation, to satisfy the FK constraint.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations.entities import Conversation, Message
from app.domain.enums import MessageRole, MessageStatus
from app.domain.errors import ScopeViolationError
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.repositories.conversation import SqlConversationRepository


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


def _make_conv(
    scope: ScopeContext,
    *,
    title: str = "Test Conversation",
    age_seconds: int = 0,
) -> Conversation:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Conversation(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        title=title,
        created_at=ts,
        updated_at=ts,
    )


def _make_msg(
    scope: ScopeContext,
    conv_id: uuid.UUID,
    *,
    role: MessageRole = MessageRole.USER,
    age_seconds: int = 0,
) -> Message:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Message(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        role=role,
        status=MessageStatus.RECEIVED,
        content=UntrustedText("Hello, tutor!"),
        created_at=ts,
        updated_at=ts,
    )


def _repo(scope: ScopeContext, session: AsyncSession) -> SqlConversationRepository:
    return SqlConversationRepository(scope=scope, session=session)


async def _save_kb(scope: ScopeContext, session: AsyncSession) -> None:
    now = datetime.now(UTC)
    session.add(
        KnowledgeBaseModel(
            id=scope.knowledge_base_id,
            user_id=scope.user_id,
            name="KB",
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_matching_conversation(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        await _repo(scope, sqlite_session).save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope, conv.id)

        assert result is not None
        assert result.id == conv.id
        assert result.title == conv.title

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get(scope, uuid.uuid4())
        assert result is None

    async def test_user_isolation_blocks_cross_user_read(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        conv = _make_conv(scope_a)
        await _repo(scope_a, sqlite_session).save(scope_a, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope_b, sqlite_session).get(scope_b, conv.id)
        assert result is None


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    async def test_insert_then_get(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        await _repo(scope, sqlite_session).save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope, conv.id)
        assert result is not None
        assert result.id == conv.id

    async def test_update_existing(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope, title="Original")
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        updated = replace(conv, title="Renamed", updated_at=datetime.now(UTC))
        await repo.save(scope, updated)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get(scope, conv.id)
        assert result is not None
        assert result.title == "Renamed"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    async def test_returns_all_conversations_for_scope(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        for i in range(3):
            await repo.save(scope, _make_conv(scope, title=f"Conv {i}"))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list(scope)
        assert len(results) == 3

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, _make_conv(scope, title="Older", age_seconds=60))
        await repo.save(scope, _make_conv(scope, title="Newer", age_seconds=0))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list(scope)
        assert results[0].title == "Newer"
        assert results[1].title == "Older"

    async def test_user_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        await _repo(scope_a, sqlite_session).save(scope_a, _make_conv(scope_a))
        await _repo(scope_b, sqlite_session).save(scope_b, _make_conv(scope_b))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list(scope_a)
        assert len(results) == 1
        assert results[0].user_id == scope_a.user_id


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_removes_conversation(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        await repo.delete(scope, conv.id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo.get(scope, conv.id) is None

    async def test_delete_is_scoped_by_user(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        conv = _make_conv(scope_a)
        await _repo(scope_a, sqlite_session).save(scope_a, conv)
        await sqlite_session.flush()

        await _repo(scope_b, sqlite_session).delete(scope_b, conv.id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await _repo(scope_a, sqlite_session).get(scope_a, conv.id) is not None


# ---------------------------------------------------------------------------
# get_message / save_message
# ---------------------------------------------------------------------------


class TestMessage:
    async def test_save_then_get_message(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_message(scope, msg.id)
        assert result is not None
        assert result.id == msg.id
        assert result.content == UntrustedText("Hello, tutor!")

    async def test_get_message_returns_none_when_absent(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get_message(scope, uuid.uuid4())
        assert result is None

    async def test_save_message_update(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        now = datetime.now(UTC)
        updated = msg.mark_processing(now=now)
        await repo.save_message(scope, updated)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_message(scope, msg.id)
        assert result is not None
        assert result.status == MessageStatus.PROCESSING


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    async def test_returns_messages_for_conversation(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        for _ in range(3):
            await repo.save_message(scope, _make_msg(scope, conv.id))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv.id)
        assert len(results) == 3

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        await repo.save_message(scope, _make_msg(scope, conv.id, age_seconds=60))
        await repo.save_message(scope, _make_msg(scope, conv.id, age_seconds=0))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv.id)
        assert results[0].created_at > results[1].created_at

    async def test_respects_limit(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        for i in range(5):
            await repo.save_message(
                scope, _make_msg(scope, conv.id, age_seconds=5 - i)
            )
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv.id, limit=3)
        assert len(results) == 3

    async def test_excludes_other_conversations(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv_a = _make_conv(scope, title="A")
        conv_b = _make_conv(scope, title="B")
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv_a)
        await repo.save(scope, conv_b)
        await sqlite_session.flush()
        await repo.save_message(scope, _make_msg(scope, conv_a.id))
        await repo.save_message(scope, _make_msg(scope, conv_b.id))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv_a.id)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Scope guard — a call carrying someone else's scope never reaches the session
# ---------------------------------------------------------------------------


class TestConversationScopeGuard:
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
            await repo.save(_make_scope(), _make_conv(scope))
        session.merge.assert_not_called()

    async def test_list_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list(_make_scope())
        session.execute.assert_not_called()

    async def test_delete_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.delete(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_get_message_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.get_message(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_message_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_message(_make_scope(), _make_msg(scope, uuid.uuid4()))
        session.merge.assert_not_called()

    async def test_list_messages_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_messages(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()
