"""Unit tests for ExpireMemoryUseCase."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from app.application.commands.expire_memory import (
    ExpireMemoryCommand,
    ExpireMemoryUseCase,
)
from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext

_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_CUTOFF = _NOW


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_fact(
    scope: ScopeContext,
    *,
    key: str = "exam_date",
    expires_at: datetime | None = _NOW - timedelta(hours=1),
    status: MemoryStatus = MemoryStatus.ACTIVE,
) -> MemoryFact:
    return MemoryFact(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        memory_type=MemoryType.EXAM_DATE,
        key=key,
        value={"date": "2026-08-01"},
        confidence=0.9,
        provenance=MemoryProvenance.USER_STATEMENT,
        status=status,
        created_at=_NOW - timedelta(days=30),
        updated_at=_NOW - timedelta(days=1),
        valid_from=_NOW - timedelta(days=30),
        expires_at=expires_at,
    )


def _use_case(*, expiring: list[MemoryFact]) -> tuple[ExpireMemoryUseCase, AsyncMock]:
    repo = AsyncMock()
    repo.list_expiring = AsyncMock(return_value=expiring)
    repo.save_batch = AsyncMock()
    return ExpireMemoryUseCase(memory_repo=repo), repo


# ---------------------------------------------------------------------------
# No expiring facts
# ---------------------------------------------------------------------------


class TestNoExpiringFacts:
    async def test_returns_zero_when_nothing_due(self) -> None:
        scope = _make_scope()
        uc, repo = _use_case(expiring=[])
        result = await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        assert result.expired == 0
        repo.save_batch.assert_not_called()

    async def test_passes_scope_and_cutoff_to_list_expiring(self) -> None:
        scope = _make_scope()
        uc, repo = _use_case(expiring=[])
        await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        repo.list_expiring.assert_awaited_once_with(scope, before=_CUTOFF)


# ---------------------------------------------------------------------------
# Expiry transitions
# ---------------------------------------------------------------------------


class TestExpiryTransitions:
    async def test_single_fact_is_marked_expired(self) -> None:
        scope = _make_scope()
        fact = _make_fact(scope)
        uc, repo = _use_case(expiring=[fact])
        result = await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        assert result.expired == 1
        repo.save_batch.assert_awaited_once()
        saved = repo.save_batch.call_args[0][1]
        assert len(saved) == 1
        assert saved[0].status is MemoryStatus.EXPIRED
        assert saved[0].id == fact.id

    async def test_multiple_facts_are_all_expired(self) -> None:
        scope = _make_scope()
        facts = [_make_fact(scope, key=f"k{i}") for i in range(3)]
        uc, repo = _use_case(expiring=facts)
        result = await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        assert result.expired == 3
        saved = repo.save_batch.call_args[0][1]
        assert all(f.status is MemoryStatus.EXPIRED for f in saved)

    async def test_expired_facts_preserve_id_and_key(self) -> None:
        scope = _make_scope()
        fact = _make_fact(scope, key="study_goal")
        uc, repo = _use_case(expiring=[fact])
        await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        saved = repo.save_batch.call_args[0][1]
        assert saved[0].id == fact.id
        assert saved[0].key == "study_goal"

    async def test_expired_facts_have_updated_at_equal_to_cutoff(self) -> None:
        scope = _make_scope()
        fact = _make_fact(scope)
        uc, repo = _use_case(expiring=[fact])
        await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        saved = repo.save_batch.call_args[0][1]
        assert saved[0].updated_at == _CUTOFF

    async def test_save_batch_called_with_scope(self) -> None:
        scope = _make_scope()
        fact = _make_fact(scope)
        uc, repo = _use_case(expiring=[fact])
        await uc.execute(ExpireMemoryCommand(scope=scope, cutoff=_CUTOFF))
        assert repo.save_batch.call_args[0][0] is scope
