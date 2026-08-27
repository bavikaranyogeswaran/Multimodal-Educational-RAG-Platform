"""Tests for SqlMemoryRepository search methods: update_embedding, dense_search, keyword_search.

All tests use a mock AsyncSession — no real database or pgvector calls are made.
Tests verify that each method builds the right SQL statement structure and
rejects requests carrying a foreign scope before touching the session.

The update_embedding test also verifies the UPDATE is not executed when the scope check fails.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.errors import ScopeViolationError
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.conversation import MemoryFactModel
from app.infrastructure.database.repositories.memory import SqlMemoryRepository

_EMBEDDING = [0.1] * 384


def _make_scope(
    *,
    user_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
) -> ScopeContext:
    return ScopeContext(
        user_id=user_id or uuid.uuid4(),
        knowledge_base_id=kb_id or uuid.uuid4(),
    )


def _make_model(scope: ScopeContext) -> MemoryFactModel:
    now = datetime.now(UTC)
    return MemoryFactModel(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        memory_type=MemoryType.GOAL.value,
        key="study_goal",
        value={"text": "Focus on photosynthesis."},
        confidence=0.9,
        provenance=int(MemoryProvenance.USER_STATEMENT),
        status=MemoryStatus.ACTIVE.value,
        created_at=now,
        updated_at=now,
        valid_from=now,
    )


def _mock_execute_pairs(rows: list[tuple]) -> MagicMock:
    """Mock execute() result whose .all() returns (model, scalar) tuples."""
    result = MagicMock()
    result.all.return_value = rows
    return result


def _mock_execute_scalars(rows: list) -> MagicMock:
    """Mock execute() result whose .scalars().all() returns a plain list."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _repo(scope: ScopeContext, session: AsyncMock) -> SqlMemoryRepository:
    return SqlMemoryRepository(scope=scope, session=session)


# ---------------------------------------------------------------------------
# update_embedding
# ---------------------------------------------------------------------------


class TestUpdateEmbedding:
    async def test_issues_update_statement(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        fact_id = uuid.uuid4()

        await _repo(scope, session).update_embedding(scope, fact_id, _EMBEDDING)

        session.execute.assert_awaited_once()

    async def test_update_targets_the_correct_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        fact_id = uuid.uuid4()

        await _repo(scope, session).update_embedding(scope, fact_id, _EMBEDDING)

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.update_embedding(_make_scope(), uuid.uuid4(), _EMBEDDING)
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# dense_search
# ---------------------------------------------------------------------------


class TestDenseSearch:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).dense_search(scope, _EMBEDDING, limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_filters_to_active_status(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).dense_search(scope, _EMBEDDING, limit=5)

        compiled = str(
            session.execute.call_args[0][0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "ACTIVE" in compiled

    async def test_excludes_null_embeddings(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).dense_search(scope, _EMBEDDING, limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "embedding" in compiled
        assert "NULL" in compiled.upper()

    async def test_orders_by_cosine_distance(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).dense_search(scope, _EMBEDDING, limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        # pgvector cosine distance uses the <=> operator
        assert "<=>" in compiled

    async def test_applies_limit(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).dense_search(scope, _EMBEDDING, limit=7)

        compiled = str(
            session.execute.call_args[0][0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "7" in compiled

    async def test_returns_fact_distance_pairs(self) -> None:
        scope = _make_scope()
        model = _make_model(scope)
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_mock_execute_pairs([(model, 0.12)])
        )

        results = await _repo(scope, session).dense_search(scope, _EMBEDDING, limit=5)

        assert len(results) == 1
        fact, distance = results[0]
        assert fact.key == model.key
        assert abs(distance - 0.12) < 1e-9

    async def test_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.dense_search(_make_scope(), _EMBEDDING, limit=5)
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# keyword_search
# ---------------------------------------------------------------------------


class TestKeywordSearch:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_filters_to_active_status(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=5)

        # REGCONFIG-typed args prevent literal_binds=True; check params dict instead.
        compiled = session.execute.call_args[0][0].compile()
        assert "ACTIVE" in compiled.params.values()

    async def test_uses_tsquery_match_operator(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "@@" in compiled

    async def test_uses_plainto_tsquery(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "plainto_tsquery" in compiled

    async def test_scores_with_ts_rank_cd(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "ts_rank_cd" in compiled

    async def test_references_tsv_column(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=5)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "tsv" in compiled

    async def test_applies_limit(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_pairs([]))

        await _repo(scope, session).keyword_search(scope, "photosynthesis", limit=10)

        # REGCONFIG-typed args prevent literal_binds=True; check params dict instead.
        compiled = session.execute.call_args[0][0].compile()
        assert 10 in compiled.params.values()

    async def test_returns_fact_score_pairs(self) -> None:
        scope = _make_scope()
        model = _make_model(scope)
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_mock_execute_pairs([(model, 0.45)])
        )

        results = await _repo(scope, session).keyword_search(
            scope, "photosynthesis", limit=5
        )

        assert len(results) == 1
        fact, score = results[0]
        assert fact.key == model.key
        assert abs(score - 0.45) < 1e-9

    async def test_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.keyword_search(_make_scope(), "test", limit=5)
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# list_expiring
# ---------------------------------------------------------------------------


class TestListExpiring:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_scalars([]))
        cutoff = datetime.now(UTC)

        await _repo(scope, session).list_expiring(scope, before=cutoff)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_filters_to_active_status(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_scalars([]))
        cutoff = datetime.now(UTC)

        await _repo(scope, session).list_expiring(scope, before=cutoff)

        compiled = str(
            session.execute.call_args[0][0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "ACTIVE" in compiled

    async def test_includes_expires_at_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_scalars([]))
        cutoff = datetime.now(UTC)

        await _repo(scope, session).list_expiring(scope, before=cutoff)

        compiled = str(session.execute.call_args[0][0].compile())
        assert "expires_at" in compiled

    async def test_returns_entities(self) -> None:
        scope = _make_scope()
        model = _make_model(scope)
        model.expires_at = datetime.now(UTC)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_execute_scalars([model]))

        results = await _repo(scope, session).list_expiring(scope, before=datetime.now(UTC))

        assert len(results) == 1
        assert results[0].key == model.key

    async def test_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_expiring(_make_scope(), before=datetime.now(UTC))
        session.execute.assert_not_called()
