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


@pytest.mark.security
@pytest.mark.gate
async def test_concept_map_subgraph_rel_query_binds_user_id() -> None:
    """The first execute (relationships one-hop expansion) must carry the scope."""
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).concept_map_subgraph(
        scope, frozenset({uuid.uuid4()}), max_nodes=10
    )
    assert scope.user_id in _params(ses, call_index=0).values()


@pytest.mark.security
@pytest.mark.gate
async def test_concept_map_subgraph_rel_query_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).concept_map_subgraph(
        scope, frozenset({uuid.uuid4()}), max_nodes=10
    )
    assert scope.knowledge_base_id in _params(ses, call_index=0).values()


@pytest.mark.security
@pytest.mark.gate
async def test_concept_map_subgraph_entity_query_binds_user_id() -> None:
    """The second execute (entity load for the capped set) must also carry the scope."""
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).concept_map_subgraph(
        scope, frozenset({uuid.uuid4()}), max_nodes=10
    )
    assert scope.user_id in _params(ses, call_index=1).values()


@pytest.mark.security
@pytest.mark.gate
async def test_concept_map_subgraph_entity_query_binds_knowledge_base_id() -> None:
    scope = _scope()
    ses = _session()
    await SqlGraphRepository(scope, ses).concept_map_subgraph(
        scope, frozenset({uuid.uuid4()}), max_nodes=10
    )
    assert scope.knowledge_base_id in _params(ses, call_index=1).values()


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
