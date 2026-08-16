"""Security tests: scope isolation and document-status enforcement in retrieval.

Verifies three invariants that must hold for every search call to
SqlDenseRetriever and SqlKeywordRetriever, regardless of what RetrievalFilters
the caller supplies:

  1. Cross-KB isolation — the authenticated scope's user_id and knowledge_base_id
     are bound as SQL parameters on every query. A call-scope that differs from the
     bound scope is rejected before any DB round-trip.

  2. Non-COMPLETED document filter — 'COMPLETED' is always bound as a status
     parameter. Chunks from PROCESSING, FAILED, DELETING, or PENDING documents are
     structurally excluded by the SQL JOIN — not filtered afterwards in application
     code, where a missing filter would silently expose them.

  3. Empty RetrievalFilters cannot bypass scope — passing RetrievalFilters() with
     no optional fields set must not weaken the user_id / knowledge_base_id
     predicates.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.errors import ScopeViolationError
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.retrieval.dense import SqlDenseRetriever
from app.infrastructure.retrieval.keyword import SqlKeywordRetriever

_QUERY_VECTOR = [0.1] * 384
_QUERY_TEXT = "what is backpropagation"
_NON_COMPLETED_STATUSES = ("PROCESSING", "FAILED", "DELETING", "PENDING")


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _session() -> AsyncMock:
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# 1. Cross-KB isolation
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_dense_binds_user_id_as_sql_parameter() -> None:
    """user_id must reach the database as a bound parameter, not a literal or absent."""
    scope = _scope()
    ses = _session()

    await SqlDenseRetriever(scope=scope, session=ses).search(
        scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_dense_binds_knowledge_base_id_as_sql_parameter() -> None:
    """knowledge_base_id must reach the database as a bound parameter."""
    scope = _scope()
    ses = _session()

    await SqlDenseRetriever(scope=scope, session=ses).search(
        scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_dense_foreign_scope_blocked_before_any_db_call() -> None:
    """A call with a scope different from the bound scope must raise before SQL runs."""
    bound_scope = _scope()
    call_scope = _scope()  # different user_id and knowledge_base_id
    ses = _session()

    retriever = SqlDenseRetriever(scope=bound_scope, session=ses)

    with pytest.raises(ScopeViolationError):
        await retriever.search(call_scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters())

    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_keyword_binds_user_id_as_sql_parameter() -> None:
    """user_id must reach the database as a bound parameter for keyword search."""
    scope = _scope()
    ses = _session()

    await SqlKeywordRetriever(scope=scope, session=ses).search(
        scope, _QUERY_TEXT, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_keyword_binds_knowledge_base_id_as_sql_parameter() -> None:
    """knowledge_base_id must reach the database as a bound parameter for keyword search."""
    scope = _scope()
    ses = _session()

    await SqlKeywordRetriever(scope=scope, session=ses).search(
        scope, _QUERY_TEXT, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert scope.knowledge_base_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_keyword_foreign_scope_blocked_before_any_db_call() -> None:
    """A mismatched call-scope must raise before any SQL runs for keyword search."""
    bound_scope = _scope()
    call_scope = _scope()
    ses = _session()

    retriever = SqlKeywordRetriever(scope=bound_scope, session=ses)

    with pytest.raises(ScopeViolationError):
        await retriever.search(call_scope, _QUERY_TEXT, top_k=5, filters=RetrievalFilters())

    ses.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Non-COMPLETED document filter
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_dense_completed_status_bound_as_sql_parameter() -> None:
    """'COMPLETED' must be a bound SQL parameter so the filter cannot be vacuously removed."""
    scope = _scope()
    ses = _session()

    await SqlDenseRetriever(scope=scope, session=ses).search(
        scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert "COMPLETED" in params.values()


@pytest.mark.security
@pytest.mark.gate
@pytest.mark.parametrize("status", _NON_COMPLETED_STATUSES)
async def test_dense_non_completed_status_absent_from_query_params(status: str) -> None:
    """No non-COMPLETED status must appear as a parameter — only COMPLETED is the gate."""
    scope = _scope()
    ses = _session()

    await SqlDenseRetriever(scope=scope, session=ses).search(
        scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert status not in params.values(), (
        f"Status '{status}' must not appear in retrieval query params — "
        "only 'COMPLETED' documents must ever be returned"
    )


@pytest.mark.security
@pytest.mark.gate
async def test_keyword_completed_status_bound_as_sql_parameter() -> None:
    """'COMPLETED' must be a bound SQL parameter for keyword search."""
    scope = _scope()
    ses = _session()

    await SqlKeywordRetriever(scope=scope, session=ses).search(
        scope, _QUERY_TEXT, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert "COMPLETED" in params.values()


@pytest.mark.security
@pytest.mark.gate
@pytest.mark.parametrize("status", _NON_COMPLETED_STATUSES)
async def test_keyword_non_completed_status_absent_from_query_params(status: str) -> None:
    """No non-COMPLETED status must appear as a parameter for keyword search."""
    scope = _scope()
    ses = _session()

    await SqlKeywordRetriever(scope=scope, session=ses).search(
        scope, _QUERY_TEXT, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert status not in params.values()


# ---------------------------------------------------------------------------
# 3. Empty RetrievalFilters cannot bypass scope
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_dense_empty_filters_preserve_all_three_mandatory_params() -> None:
    """RetrievalFilters() with no optional fields must not relax any scope predicate."""
    scope = _scope()
    ses = _session()

    await SqlDenseRetriever(scope=scope, session=ses).search(
        scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values(), "user_id absent despite empty filters"
    assert scope.knowledge_base_id in params.values(), "knowledge_base_id absent despite empty filters"
    assert "COMPLETED" in params.values(), "COMPLETED status filter absent despite empty filters"


@pytest.mark.security
@pytest.mark.gate
async def test_keyword_empty_filters_preserve_all_three_mandatory_params() -> None:
    """RetrievalFilters() with no optional fields must not relax any scope predicate."""
    scope = _scope()
    ses = _session()

    await SqlKeywordRetriever(scope=scope, session=ses).search(
        scope, _QUERY_TEXT, top_k=5, filters=RetrievalFilters()
    )

    params = ses.execute.call_args[0][0].compile().params
    assert scope.user_id in params.values(), "user_id absent despite empty filters"
    assert scope.knowledge_base_id in params.values(), "knowledge_base_id absent despite empty filters"
    assert "COMPLETED" in params.values(), "COMPLETED status filter absent despite empty filters"
