"""Unit tests for the async session factory and ScopedRepository base.

Runs without a live database. Engine tests use a dummy URL (lazy — no
connection is made); repository tests use a MagicMock session.
"""

from __future__ import annotations

import dataclasses
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import ClauseElement
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import QueuePool

from app.domain.errors import InvariantViolationError, ScopeViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import (
    _normalise_url,
    build_engine,
    build_session_factory,
)

# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------


class TestNormaliseUrl:
    def test_plain_postgresql_scheme_gets_psycopg_driver(self) -> None:
        assert _normalise_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"

    def test_plain_postgres_scheme_gets_psycopg_driver(self) -> None:
        assert _normalise_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"

    def test_psycopg_scheme_is_unchanged(self) -> None:
        url = "postgresql+psycopg://u:p@h:5432/db"
        assert _normalise_url(url) == url

    def test_asyncpg_scheme_is_unchanged(self) -> None:
        url = "postgresql+asyncpg://u:p@h:5432/db"
        assert _normalise_url(url) == url

    def test_empty_string_is_unchanged(self) -> None:
        assert _normalise_url("") == ""


# ---------------------------------------------------------------------------
# Engine and session factory
# ---------------------------------------------------------------------------


class TestBuildEngine:
    def test_returns_async_engine(self) -> None:
        from pydantic import SecretStr

        from app.configuration.settings import DatabaseSettings

        settings = DatabaseSettings(url=SecretStr("postgresql+psycopg://u:p@h:5432/db"))
        engine = build_engine(settings)
        assert isinstance(engine, AsyncEngine)

    def test_pool_size_is_applied(self) -> None:
        from pydantic import SecretStr

        from app.configuration.settings import DatabaseSettings

        settings = DatabaseSettings(
            url=SecretStr("postgresql+psycopg://u:p@h:5432/db"), pool_size=3
        )
        engine = build_engine(settings)
        # Async engines get AsyncAdaptedQueuePool, a QueuePool subclass; only the
        # QueuePool branch of the hierarchy exposes size().
        pool = engine.pool
        assert isinstance(pool, QueuePool)
        assert pool.size() == 3


class TestBuildSessionFactory:
    def test_returns_async_sessionmaker(self) -> None:
        from pydantic import SecretStr

        from app.configuration.settings import DatabaseSettings

        settings = DatabaseSettings(url=SecretStr("postgresql+psycopg://u:p@h:5432/db"))
        factory = build_session_factory(build_engine(settings))
        assert isinstance(factory, async_sessionmaker)

    def test_expire_on_commit_is_false(self) -> None:
        from pydantic import SecretStr

        from app.configuration.settings import DatabaseSettings

        settings = DatabaseSettings(url=SecretStr("postgresql+psycopg://u:p@h:5432/db"))
        factory = build_session_factory(build_engine(settings))
        assert factory.kw.get("expire_on_commit") is False


# ---------------------------------------------------------------------------
# Container integration
# ---------------------------------------------------------------------------


class TestContainerSessionFactory:
    def test_container_has_session_factory_field(self) -> None:
        from app.configuration.container import Container

        field_names = {f.name for f in dataclasses.fields(Container)}
        assert "session_factory" in field_names

    def test_build_container_wires_session_factory_when_url_present(self) -> None:
        from pydantic import SecretStr

        from app.configuration.settings import DatabaseSettings, Settings
        from app.configuration.wire import build_container

        settings = Settings(
            database=DatabaseSettings(url=SecretStr("postgresql+psycopg://u:p@h:5432/db"))
        )
        container = build_container(settings)
        assert isinstance(container.session_factory, async_sessionmaker)

    def test_build_container_constructs_without_error(self) -> None:
        # Smoke test: Container must construct even when no database is configured.
        # The session_factory slot holds either a real factory (if DATABASE_URL is
        # present in .env) or a stub — either way the Container is valid.
        from app.configuration.container import Container
        from app.configuration.settings import Settings
        from app.configuration.wire import build_container

        container = build_container(Settings())
        assert isinstance(container, Container)
        assert hasattr(container, "session_factory")


# ---------------------------------------------------------------------------
# ScopedRepository construction
# ---------------------------------------------------------------------------


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_repo(scope: ScopeContext) -> object:
    from app.infrastructure.database.repository import ScopedRepository

    class _Concrete(ScopedRepository):
        pass

    return _Concrete(scope=scope, session=MagicMock(spec=AsyncSession))


class TestScopedRepositoryInit:
    def test_valid_scope_is_stored(self) -> None:
        scope = _make_scope()
        repo = _make_repo(scope)
        assert repo._scope is scope  # type: ignore[attr-defined]

    def test_session_is_stored(self) -> None:
        scope = _make_scope()
        mock_session = MagicMock(spec=AsyncSession)

        from app.infrastructure.database.repository import ScopedRepository

        class _Concrete(ScopedRepository):
            pass

        repo = _Concrete(scope=scope, session=mock_session)
        assert repo._session is mock_session

    def test_string_scope_raises_invariant_error(self) -> None:
        from app.infrastructure.database.repository import ScopedRepository

        class _Concrete(ScopedRepository):
            pass

        with pytest.raises(InvariantViolationError):
            _Concrete(scope="not-a-scope", session=MagicMock())  # type: ignore[arg-type]

    def test_none_scope_raises_invariant_error(self) -> None:
        from app.infrastructure.database.repository import ScopedRepository

        class _Concrete(ScopedRepository):
            pass

        with pytest.raises(InvariantViolationError):
            _Concrete(scope=None, session=MagicMock())  # type: ignore[arg-type]

    def test_nil_user_id_raises_invariant_error_at_scope_construction(self) -> None:
        with pytest.raises(InvariantViolationError):
            ScopeContext(user_id=uuid.UUID(int=0), knowledge_base_id=uuid.uuid4())

    def test_nil_knowledge_base_id_raises_invariant_error_at_scope_construction(self) -> None:
        with pytest.raises(InvariantViolationError):
            ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.UUID(int=0))


# ---------------------------------------------------------------------------
# ScopedRepository scope guard
# ---------------------------------------------------------------------------


class TestScopedRepositoryRequireScope:
    def test_same_scope_object_passes(self) -> None:
        scope = _make_scope()
        repo = _make_repo(scope)
        assert repo._require_scope(scope) is None  # type: ignore[attr-defined]

    def test_equal_scope_value_passes(self) -> None:
        # Identity is not the test — a separate instance carrying the same two ids
        # denotes the same boundary and must be accepted.
        scope = _make_scope()
        repo = _make_repo(scope)
        twin = ScopeContext(
            user_id=scope.user_id, knowledge_base_id=scope.knowledge_base_id
        )
        assert repo._require_scope(twin) is None  # type: ignore[attr-defined]

    def test_foreign_user_raises_scope_violation(self) -> None:
        scope = _make_scope()
        repo = _make_repo(scope)
        intruder = ScopeContext(
            user_id=uuid.uuid4(), knowledge_base_id=scope.knowledge_base_id
        )
        with pytest.raises(ScopeViolationError):
            repo._require_scope(intruder)  # type: ignore[attr-defined]

    def test_foreign_knowledge_base_raises_scope_violation(self) -> None:
        scope = _make_scope()
        repo = _make_repo(scope)
        other_kb = ScopeContext(user_id=scope.user_id, knowledge_base_id=uuid.uuid4())
        with pytest.raises(ScopeViolationError):
            repo._require_scope(other_kb)  # type: ignore[attr-defined]

    def test_violation_carries_expected_and_actual_ids(self) -> None:
        scope = _make_scope()
        repo = _make_repo(scope)
        intruder = _make_scope()

        with pytest.raises(ScopeViolationError) as excinfo:
            repo._require_scope(intruder)  # type: ignore[attr-defined]

        error = excinfo.value
        assert error.expected_user_id == scope.user_id
        assert error.expected_knowledge_base_id == scope.knowledge_base_id
        assert error.actual_user_id == intruder.user_id
        assert error.actual_knowledge_base_id == intruder.knowledge_base_id

    def test_violation_names_the_repository_class(self) -> None:
        scope = _make_scope()
        repo = _make_repo(scope)

        with pytest.raises(ScopeViolationError) as excinfo:
            repo._require_scope(_make_scope())  # type: ignore[attr-defined]

        assert "_Concrete" in str(excinfo.value)


# ---------------------------------------------------------------------------
# ScopedRepository filter helpers
# ---------------------------------------------------------------------------


class TestScopedRepositoryFilters:
    def test_scope_filter_is_a_clause_element(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        repo = _make_repo(_make_scope())
        expr = repo._scope_filter(ChunkModel)  # type: ignore[attr-defined]
        assert isinstance(expr, ClauseElement)

    def test_scope_filter_references_user_id(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        repo = _make_repo(_make_scope())
        expr = repo._scope_filter(ChunkModel)  # type: ignore[attr-defined]
        assert "user_id" in str(expr.compile())

    def test_scope_filter_references_knowledge_base_id(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        repo = _make_repo(_make_scope())
        expr = repo._scope_filter(ChunkModel)  # type: ignore[attr-defined]
        assert "knowledge_base_id" in str(expr.compile())

    def test_user_filter_is_a_clause_element(self) -> None:
        from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel

        repo = _make_repo(_make_scope())
        expr = repo._user_filter(KnowledgeBaseModel)  # type: ignore[attr-defined]
        assert isinstance(expr, ClauseElement)

    def test_user_filter_references_user_id(self) -> None:
        from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel

        repo = _make_repo(_make_scope())
        expr = repo._user_filter(KnowledgeBaseModel)  # type: ignore[attr-defined]
        assert "user_id" in str(expr.compile())

    def test_scope_filter_binds_scope_user_id(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        scope = _make_scope()
        repo = _make_repo(scope)
        expr = repo._scope_filter(ChunkModel)  # type: ignore[attr-defined]
        compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
        # SQLAlchemy renders UUIDs without hyphens in literal_binds mode
        assert str(scope.user_id).replace("-", "") in compiled

    def test_scope_filter_binds_scope_knowledge_base_id(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        scope = _make_scope()
        repo = _make_repo(scope)
        expr = repo._scope_filter(ChunkModel)  # type: ignore[attr-defined]
        compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
        assert str(scope.knowledge_base_id).replace("-", "") in compiled
