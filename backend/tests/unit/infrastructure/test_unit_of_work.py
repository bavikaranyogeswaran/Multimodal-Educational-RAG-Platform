"""Tests for build_conversation_unit_of_work.

The point of the unit of work is that it owns its session rather than borrowing one,
so these tests are about lifecycle: a fresh session per block, a commit when the block
completes, no commit when it raises, and the bound scope reaching the repository.

The session factory is a mock. What is being tested is when commit and close are called
relative to the block, which is observable without a database.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.errors import ScopeViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.unit_of_work import build_conversation_unit_of_work


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _factory(sessions: list[AsyncMock] | None = None) -> MagicMock:
    """A session factory whose result works as `async with factory() as session`."""

    def _make() -> MagicMock:
        session = AsyncMock()
        if sessions is not None:
            sessions.append(session)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    return MagicMock(side_effect=_make)


class TestUnitOfWorkLifecycle:
    async def test_yields_a_conversation_repository(self) -> None:
        uow = build_conversation_unit_of_work(_factory(), _scope())

        async with uow() as repo:
            assert isinstance(repo, SqlConversationRepository)

    async def test_commits_when_the_block_completes(self) -> None:
        sessions: list[AsyncMock] = []
        uow = build_conversation_unit_of_work(_factory(sessions), _scope())

        async with uow():
            pass

        sessions[0].commit.assert_awaited_once()

    async def test_does_not_commit_when_the_block_raises(self) -> None:
        sessions: list[AsyncMock] = []
        uow = build_conversation_unit_of_work(_factory(sessions), _scope())

        with pytest.raises(RuntimeError):
            async with uow():
                raise RuntimeError("write failed")

        # Committing a half-finished change would persist exactly the state the
        # exception says is wrong.
        sessions[0].commit.assert_not_awaited()

    async def test_commit_happens_after_the_block_body(self) -> None:
        order: list[str] = []
        sessions: list[AsyncMock] = []
        uow = build_conversation_unit_of_work(_factory(sessions), _scope())

        async with uow():
            order.append("body")
            sessions[0].commit = AsyncMock(side_effect=lambda: order.append("commit"))

        assert order == ["body", "commit"]

    async def test_each_block_opens_its_own_session(self) -> None:
        factory = _factory()
        uow = build_conversation_unit_of_work(factory, _scope())

        async with uow():
            pass
        async with uow():
            pass

        # Two blocks separated by the end of a request cannot share a session — that
        # is the whole reason the boundary moved here.
        assert factory.call_count == 2

    async def test_repository_is_bound_to_the_scope_given_here(self) -> None:
        uow = build_conversation_unit_of_work(_factory(), _scope())

        async with uow() as repo:
            # Asserted through behaviour rather than by reading the bound scope: a call
            # under someone else's scope is refused, which can only happen if the scope
            # supplied to the builder is the one the repository ended up with.
            with pytest.raises(ScopeViolationError):
                await repo.get(_scope(), uuid.uuid4())
