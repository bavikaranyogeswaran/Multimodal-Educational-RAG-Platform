"""Security tests: cross-KB isolation in SqlGraphRepository.

Verifies two invariants for every read/write operation:

  1. Scope parameters — user_id and knowledge_base_id are bound as SQL
     parameters on every query. Scope data never travels as a literal or
     sits absent in the WHERE clause.

  2. Foreign-scope rejection — a call whose scope differs from the repository's
     bound scope raises ScopeViolationError before any DB round-trip.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.errors import ScopeViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.graph import SqlGraphRepository


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
    return session


def _params(session: AsyncMock, *, call_index: int = 0) -> dict:
    """Extract bound SQL parameters from the Nth execute call."""
    return session.execute.call_args_list[call_index][0][0].compile().params


# ---------------------------------------------------------------------------
# 1. Scope parameters reach the database as bound values
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_get_entity_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).get_entity(scope, uuid.uuid4())
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_get_entity_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).get_entity(scope, uuid.uuid4())
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_entities_for_document_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).list_entities_for_document(scope, uuid.uuid4())
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_entities_for_document_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).list_entities_for_document(scope, uuid.uuid4())
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_find_entity_by_name_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).find_entity_by_name(scope, "Neural Network")
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_find_entity_by_name_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).find_entity_by_name(scope, "Neural Network")
    assert scope.knowledge_base_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_relationships_for_entities_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).list_relationships_for_entities(
        scope, frozenset({uuid.uuid4()})
    )
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_list_relationships_for_entities_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).list_relationships_for_entities(
        scope, frozenset({uuid.uuid4()})
    )
    assert scope.knowledge_base_id in _params(ses).values()


def _session_yielding_a_node() -> AsyncMock:
    """A session whose first read finds one node, so the later reads still run.

    The traversal returns early on an empty node set, which would leave the entity and
    relationship queries unexecuted and untested.
    """
    def _result(rows: list) -> MagicMock:
        scalars = MagicMock()
        scalars.all.return_value = rows
        result = MagicMock()
        result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = None
        return result

    # The walk finds one node; the entity and edge reads that follow it find nothing,
    # which is enough to run their queries without needing rows to convert.
    results = [_result([uuid.uuid4()])]

    session = AsyncMock()

    async def _execute(_stmt, *args, **kwargs):
        return results.pop(0) if results else _result([])

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _all_params(session: AsyncMock) -> list[dict]:
    return [call[0][0].compile().params for call in session.execute.call_args_list]


@pytest.mark.security
@pytest.mark.gate
async def test_every_concept_map_query_binds_the_scope() -> None:
    """Asserted over all queries rather than by position.

    Pinning "the second execute" is how a scope check gets lost: the method's query
    plan changed, and the test that named a position broke while a test that named the
    property would have kept holding. Concept-map assembly reads entities, edges, and
    walks the graph to find them, and none of those may leave the scope behind.
    """
    scope = _scope()
    ses = _session_yielding_a_node()

    await SqlGraphRepository(scope, ses).concept_map_subgraph(
        scope, frozenset({uuid.uuid4()}), max_nodes=10
    )

    every_query = _all_params(ses)
    assert len(every_query) >= 2, "expected the traversal, the entities and the edges"
    for params in every_query:
        assert scope.user_id in params.values()
        assert scope.knowledge_base_id in params.values()


@pytest.mark.security
@pytest.mark.gate
async def test_graph_walk_carries_the_scope_into_its_recursive_step() -> None:
    """The walk joins relationships to find neighbours, and that join needs filtering.

    Scoping only the seeds would start inside the Knowledge Base and step straight out
    of it — the one place a traversal can leak that a flat query cannot.
    """
    scope = _scope()
    ses = _session_yielding_a_node()

    await SqlGraphRepository(scope, ses).concept_map_subgraph(
        scope, frozenset({uuid.uuid4()}), max_nodes=10
    )

    walk = ses.execute.call_args_list[0][0][0].compile(dialect=postgresql.dialect())
    anchor, union, recursive = str(walk).partition("UNION")

    assert union, "the traversal is expected to be a recursive walk"
    for half in (anchor, recursive):
        assert "user_id" in half
        assert "knowledge_base_id" in half


@pytest.mark.security
@pytest.mark.gate
async def test_delete_for_document_binds_user_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).delete_for_document(scope, uuid.uuid4())
    assert scope.user_id in _params(ses).values()


@pytest.mark.security
@pytest.mark.gate
async def test_delete_for_document_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).delete_for_document(scope, uuid.uuid4())
    assert scope.knowledge_base_id in _params(ses).values()


# ---------------------------------------------------------------------------
# 2. Foreign-scope rejection — ScopeViolationError before any DB round-trip
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_get_entity_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlGraphRepository(bound, ses).get_entity(foreign, uuid.uuid4())
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_list_entities_for_document_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlGraphRepository(bound, ses).list_entities_for_document(foreign, uuid.uuid4())
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_find_entity_by_name_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlGraphRepository(bound, ses).find_entity_by_name(foreign, "Backpropagation")
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_list_relationships_for_entities_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlGraphRepository(bound, ses).list_relationships_for_entities(
            foreign, frozenset({uuid.uuid4()})
        )
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_concept_map_subgraph_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlGraphRepository(bound, ses).concept_map_subgraph(
            foreign, frozenset({uuid.uuid4()}), max_nodes=10
        )
    ses.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.gate
async def test_delete_for_document_rejects_foreign_scope() -> None:
    bound, foreign = _scope(), _scope()
    ses = _session()
    with pytest.raises(ScopeViolationError):
        await SqlGraphRepository(bound, ses).delete_for_document(foreign, uuid.uuid4())
    ses.execute.assert_not_called()
