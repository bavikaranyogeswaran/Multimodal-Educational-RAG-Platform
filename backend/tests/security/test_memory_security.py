"""Security tests: cross-KB isolation and status filtering in SqlMemoryRepository.

Verifies three invariants for every read/write operation:

  1. Scope parameters — user_id and knowledge_base_id are bound as SQL
     parameters on every query. Scope data never travels as a literal or
     sits absent in the WHERE clause.

  2. Foreign-scope rejection — a call whose scope differs from the repository's
     bound scope raises ScopeViolationError before any DB round-trip.

  3. Status filtering (release gate) — list_active and list_expiring bind the
     ACTIVE status as a SQL parameter, so deleted, superseded, disputed, expired
     and unconfirmed facts are structurally excluded, not filtered in application
     code after retrieval.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import MemoryStatus
from app.domain.errors import ScopeViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.memory import SqlMemoryRepository


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _session() -> AsyncMock:
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.merge = AsyncMock()
    return session


def _params(session: AsyncMock, *, call_index: int = 0) -> dict:
    """Extract bound SQL parameters from the Nth execute call."""
    return session.execute.call_args_list[call_index][0][0].compile().params


# ---------------------------------------------------------------------------
# 1. Scope parameters reach the database as bound values
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_get_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).get(scope, uuid.uuid4())
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_get_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).get(scope, uuid.uuid4())
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_get_active_by_key_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).get_active_by_key(scope, "exam_date")
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_get_active_by_key_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).get_active_by_key(scope, "exam_date")
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_get_active_by_key_binds_active_status() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).get_active_by_key(scope, "exam_date")
    assert MemoryStatus.ACTIVE.value in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_get_active_by_key_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).get_active_by_key(foreign, "exam_date")
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_list_active_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_active(scope)
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_active_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_active(scope)
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_active_binds_active_status() -> None:
    """The ACTIVE status filter is a bound SQL parameter, not a literal.

    Removing the status predicate from list_active removes the parameter from the
    compiled output and fails this assertion. That makes an accidentally dropped
    filter visible here rather than silently returning deleted or expired facts.
    """
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_active(scope)
    assert MemoryStatus.ACTIVE.value in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_all_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_all(scope)
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_all_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_all(scope)
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_update_embedding_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).update_embedding(scope, uuid.uuid4(), [0.1, 0.2])
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_update_embedding_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).update_embedding(scope, uuid.uuid4(), [0.1, 0.2])
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_expiring_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_expiring(scope, before=datetime.now(UTC))
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_expiring_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_expiring(scope, before=datetime.now(UTC))
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_expiring_binds_active_status() -> None:
    """list_expiring only schedules expiration for ACTIVE facts.

    A fact that is already DELETED, SUPERSEDED or EXPIRED must not be returned
    by this query — the ExpireMemoryUseCase would attempt to transition it again
    and violate the entity's lifecycle invariants.
    """
    scope = _scope()
    ses = _session()
    await SqlMemoryRepository(scope, ses).list_expiring(scope, before=datetime.now(UTC))
    assert MemoryStatus.ACTIVE.value in _params(ses).values()


# ---------------------------------------------------------------------------
# 2. Foreign-scope rejection — ScopeViolationError before any DB round-trip
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_get_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).get(foreign, uuid.uuid4())
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_save_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).save(foreign, MagicMock())
    ses.merge.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_save_batch_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).save_batch(foreign, [])
    ses.merge.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_list_active_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).list_active(foreign)
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_list_all_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).list_all(foreign)
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_update_embedding_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).update_embedding(foreign, uuid.uuid4(), [0.1])
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_dense_search_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).dense_search(foreign, [0.1, 0.2], limit=10)
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_keyword_search_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).keyword_search(foreign, "entropy", limit=10)
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_list_expiring_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlMemoryRepository(bound, ses).list_expiring(foreign, before=datetime.now(UTC))
    ses.execute.assert_not_called()
