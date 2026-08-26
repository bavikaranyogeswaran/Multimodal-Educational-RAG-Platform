"""Tests for SqlGraphRepository against an in-memory SQLite database.

GraphEntityModel and GraphRelationshipModel use only standard SQL types — no
ARRAY/JSONB/Vector — so SQLite can create and populate both tables. SQLite does
not enforce foreign keys by default, so:
  - The FK from graph_entities to chunks (source_chunk_id) is satisfied by a
    random UUID; no chunks row is required.
  - The FK from graph_relationships to chunks (source_chunk_id) is satisfied the
    same way.
  - The FK from graph_relationships to graph_entities is satisfied by saving the
    linked entity first.
A KB row must be inserted before any entity save because graph_entities.knowledge_base_id
has an FK to knowledge_bases (which IS enforced in the test tables even in SQLite
when the referenced row exists). SQLite only raises FK errors when enforcement is
enabled via PRAGMA, which this fixture does not enable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.errors import ScopeViolationError
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.repositories.graph import SqlGraphRepository


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


def _make_entity(
    scope: ScopeContext,
    *,
    name: str = "Concept Alpha",
    source_document_id: uuid.UUID | None = None,
) -> GraphEntity:
    ts = datetime.now(UTC)
    return GraphEntity(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        entity_type=GraphNodeType.CONCEPT,
        name=name,
        created_at=ts,
        updated_at=ts,
        source_document_id=source_document_id,
    )


def _make_relationship(
    scope: ScopeContext,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    *,
    chunk_id: uuid.UUID | None = None,
) -> GraphRelationship:
    ts = datetime.now(UTC)
    return GraphRelationship(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type=RelationshipType.PREREQUISITE_OF,
        source_chunk_id=chunk_id or uuid.uuid4(),
        page_number=1,
        evidence=UntrustedText("Alpha must be understood before Beta."),
        created_at=ts,
        updated_at=ts,
    )


def _repo(scope: ScopeContext, session: AsyncSession) -> SqlGraphRepository:
    return SqlGraphRepository(scope=scope, session=session)


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
# get_entity
# ---------------------------------------------------------------------------


class TestGetEntity:
    async def test_returns_matching_entity(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        entity = _make_entity(scope, name="Newton's Laws")
        await _repo(scope, sqlite_session).save_entity(scope, entity)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get_entity(scope, entity.id)

        assert result is not None
        assert result.id == entity.id
        assert result.name == "Newton's Laws"
        assert result.entity_type == GraphNodeType.CONCEPT

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get_entity(scope, uuid.uuid4())
        assert result is None


# ---------------------------------------------------------------------------
# save_entity / save_entities
# ---------------------------------------------------------------------------


class TestSaveEntity:
    async def test_insert_then_get(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        entity = _make_entity(scope)
        await _repo(scope, sqlite_session).save_entity(scope, entity)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get_entity(scope, entity.id)
        assert result is not None

    async def test_update_existing(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        entity = _make_entity(scope, name="Original")
        repo = _repo(scope, sqlite_session)
        await repo.save_entity(scope, entity)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        updated = entity.renamed("Updated", now=datetime.now(UTC))
        await repo.save_entity(scope, updated)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_entity(scope, entity.id)
        assert result is not None
        assert result.name == "Updated"


class TestSaveEntities:
    async def test_saves_multiple_entities(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        entities = [_make_entity(scope, name=f"E{i}") for i in range(3)]
        repo = _repo(scope, sqlite_session)
        await repo.save_entities(scope, entities)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        for entity in entities:
            result = await repo.get_entity(scope, entity.id)
            assert result is not None


# ---------------------------------------------------------------------------
# get_relationship / save_relationship / save_relationships
# ---------------------------------------------------------------------------


class TestGetRelationship:
    async def test_returns_matching_relationship(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        src = _make_entity(scope, name="Alpha")
        tgt = _make_entity(scope, name="Beta")
        await repo.save_entities(scope, [src, tgt])
        await sqlite_session.flush()

        rel = _make_relationship(scope, src.id, tgt.id)
        await repo.save_relationship(scope, rel)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_relationship(scope, rel.id)
        assert result is not None
        assert result.id == rel.id
        assert result.relationship_type == RelationshipType.PREREQUISITE_OF
        assert result.evidence == UntrustedText("Alpha must be understood before Beta.")

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get_relationship(scope, uuid.uuid4())
        assert result is None


class TestSaveRelationship:
    async def test_round_trips_all_fields(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        src = _make_entity(scope, name="A")
        tgt = _make_entity(scope, name="B")
        await repo.save_entities(scope, [src, tgt])
        await sqlite_session.flush()

        chunk_id = uuid.uuid4()
        rel = _make_relationship(scope, src.id, tgt.id, chunk_id=chunk_id)
        await repo.save_relationship(scope, rel)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_relationship(scope, rel.id)
        assert result is not None
        assert result.source_chunk_id == chunk_id
        assert result.page_number == 1
        assert result.weight == 1.0
        assert result.extraction_confidence is None


class TestSaveRelationships:
    async def test_saves_multiple_relationships(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        entities = [_make_entity(scope, name=f"N{i}") for i in range(4)]
        await repo.save_entities(scope, entities)
        await sqlite_session.flush()

        rels = [
            _make_relationship(scope, entities[i].id, entities[i + 1].id)
            for i in range(3)
        ]
        await repo.save_relationships(scope, rels)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        for rel in rels:
            result = await repo.get_relationship(scope, rel.id)
            assert result is not None


# ---------------------------------------------------------------------------
# delete_for_document
# ---------------------------------------------------------------------------


class TestDeleteForDocument:
    async def test_removes_entities_for_document(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        doc_id = uuid.uuid4()
        entity = _make_entity(scope, source_document_id=doc_id)
        other = _make_entity(scope)
        await repo.save_entities(scope, [entity, other])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        await repo.delete_for_document(scope, doc_id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo.get_entity(scope, entity.id) is None
        assert await repo.get_entity(scope, other.id) is not None

    async def test_delete_is_scoped_by_user(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        repo_a = _repo(scope_a, sqlite_session)
        repo_b = _repo(scope_b, sqlite_session)
        doc_id = uuid.uuid4()
        entity_a = _make_entity(scope_a, source_document_id=doc_id)
        entity_b = _make_entity(scope_b, source_document_id=doc_id)
        await repo_a.save_entity(scope_a, entity_a)
        await repo_b.save_entity(scope_b, entity_b)
        await sqlite_session.flush()

        await repo_b.delete_for_document(scope_b, doc_id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo_a.get_entity(scope_a, entity_a.id) is not None
        assert await repo_b.get_entity(scope_b, entity_b.id) is None


# ---------------------------------------------------------------------------
# Scope guard
# ---------------------------------------------------------------------------


class TestGraphScopeGuard:
    async def test_get_entity_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.get_entity(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_entity_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_entity(_make_scope(), _make_entity(scope))
        session.merge.assert_not_called()

    async def test_save_entities_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_entities(_make_scope(), [_make_entity(scope)])
        session.merge.assert_not_called()

    async def test_get_relationship_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.get_relationship(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_relationship_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        ts = datetime.now(UTC)
        rel = GraphRelationship(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            source_entity_id=uuid.uuid4(),
            target_entity_id=uuid.uuid4(),
            relationship_type=RelationshipType.RELATED_TO,
            source_chunk_id=uuid.uuid4(),
            page_number=1,
            evidence=UntrustedText("evidence"),
            created_at=ts,
            updated_at=ts,
        )
        with pytest.raises(ScopeViolationError):
            await repo.save_relationship(_make_scope(), rel)
        session.merge.assert_not_called()

    async def test_delete_for_document_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.delete_for_document(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_list_entities_for_document_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_entities_for_document(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_find_entity_by_name_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.find_entity_by_name(_make_scope(), "Concept")
        session.execute.assert_not_called()

    async def test_list_relationships_for_entities_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_relationships_for_entities(_make_scope(), frozenset([uuid.uuid4()]))
        session.execute.assert_not_called()

    async def test_concept_map_subgraph_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.concept_map_subgraph(_make_scope(), frozenset([uuid.uuid4()]), max_nodes=50)
        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# list_entities_for_document
# ---------------------------------------------------------------------------


class TestListEntitiesForDocument:
    async def test_returns_entities_for_document(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        doc_id = uuid.uuid4()
        e1 = _make_entity(scope, name="Beta", source_document_id=doc_id)
        e2 = _make_entity(scope, name="Alpha", source_document_id=doc_id)
        other = _make_entity(scope, name="Gamma")
        await repo.save_entities(scope, [e1, e2, other])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_entities_for_document(scope, doc_id)

        assert len(results) == 2
        # ordered by name
        assert results[0].name == "Alpha"
        assert results[1].name == "Beta"

    async def test_returns_empty_for_unknown_document(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        results = await _repo(scope, sqlite_session).list_entities_for_document(
            scope, uuid.uuid4()
        )
        assert results == []

    async def test_excludes_other_documents(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        doc_a = uuid.uuid4()
        doc_b = uuid.uuid4()
        ea = _make_entity(scope, name="A", source_document_id=doc_a)
        eb = _make_entity(scope, name="B", source_document_id=doc_b)
        await repo.save_entities(scope, [ea, eb])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_entities_for_document(scope, doc_a)

        assert len(results) == 1
        assert results[0].id == ea.id

    async def test_scoped_to_user(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        doc_id = uuid.uuid4()
        ea = _make_entity(scope_a, source_document_id=doc_id)
        eb = _make_entity(scope_b, source_document_id=doc_id)
        await _repo(scope_a, sqlite_session).save_entity(scope_a, ea)
        await _repo(scope_b, sqlite_session).save_entity(scope_b, eb)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list_entities_for_document(scope_a, doc_id)

        assert len(results) == 1
        assert results[0].id == ea.id


# ---------------------------------------------------------------------------
# find_entity_by_name
# ---------------------------------------------------------------------------


class TestFindEntityByName:
    async def test_returns_entity_when_found(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        entity = _make_entity(scope, name="Newton's Second Law")
        await _repo(scope, sqlite_session).save_entity(scope, entity)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).find_entity_by_name(
            scope, "Newton's Second Law"
        )

        assert result is not None
        assert result.id == entity.id

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).find_entity_by_name(scope, "Nonexistent")
        assert result is None

    async def test_name_match_is_exact(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        entity = _make_entity(scope, name="Momentum")
        await _repo(scope, sqlite_session).save_entity(scope, entity)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).find_entity_by_name(scope, "momentum")

        assert result is None

    async def test_scoped_to_user(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        ea = _make_entity(scope_a, name="Entropy")
        await _repo(scope_a, sqlite_session).save_entity(scope_a, ea)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope_b, sqlite_session).find_entity_by_name(scope_b, "Entropy")

        assert result is None


# ---------------------------------------------------------------------------
# list_relationships_for_entities
# ---------------------------------------------------------------------------


class TestListRelationshipsForEntities:
    async def test_returns_empty_for_empty_ids(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        results = await _repo(scope, sqlite_session).list_relationships_for_entities(
            scope, frozenset()
        )
        assert results == []

    async def test_returns_outgoing_relationships(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        src = _make_entity(scope, name="A")
        tgt = _make_entity(scope, name="B")
        await repo.save_entities(scope, [src, tgt])
        rel = _make_relationship(scope, src.id, tgt.id)
        await repo.save_relationship(scope, rel)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_relationships_for_entities(scope, frozenset([src.id]))

        assert len(results) == 1
        assert results[0].id == rel.id

    async def test_returns_incoming_relationships(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        src = _make_entity(scope, name="A")
        tgt = _make_entity(scope, name="B")
        await repo.save_entities(scope, [src, tgt])
        rel = _make_relationship(scope, src.id, tgt.id)
        await repo.save_relationship(scope, rel)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_relationships_for_entities(scope, frozenset([tgt.id]))

        assert len(results) == 1
        assert results[0].id == rel.id

    async def test_excludes_unrelated_relationships(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        a = _make_entity(scope, name="A")
        b = _make_entity(scope, name="B")
        c = _make_entity(scope, name="C")
        await repo.save_entities(scope, [a, b, c])
        rel_ab = _make_relationship(scope, a.id, b.id)
        rel_bc = _make_relationship(scope, b.id, c.id)
        await repo.save_relationships(scope, [rel_ab, rel_bc])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        # Only A is seeded — rel_ab is touching A, rel_bc is not
        results = await repo.list_relationships_for_entities(scope, frozenset([a.id]))

        ids = {r.id for r in results}
        assert rel_ab.id in ids
        assert rel_bc.id not in ids

    async def test_does_not_duplicate_when_both_endpoints_are_seeds(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        a = _make_entity(scope, name="A")
        b = _make_entity(scope, name="B")
        await repo.save_entities(scope, [a, b])
        rel = _make_relationship(scope, a.id, b.id)
        await repo.save_relationship(scope, rel)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        # Both endpoints in seed set — relationship should appear exactly once
        results = await repo.list_relationships_for_entities(
            scope, frozenset([a.id, b.id])
        )

        assert len(results) == 1

    async def test_scoped_to_user(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        ea1 = _make_entity(scope_a, name="A1")
        ea2 = _make_entity(scope_a, name="A2")
        eb1 = _make_entity(scope_b, name="B1")
        eb2 = _make_entity(scope_b, name="B2")
        await _repo(scope_a, sqlite_session).save_entities(scope_a, [ea1, ea2])
        await _repo(scope_b, sqlite_session).save_entities(scope_b, [eb1, eb2])
        rel_a = _make_relationship(scope_a, ea1.id, ea2.id)
        rel_b = _make_relationship(scope_b, eb1.id, eb2.id)
        await _repo(scope_a, sqlite_session).save_relationship(scope_a, rel_a)
        await _repo(scope_b, sqlite_session).save_relationship(scope_b, rel_b)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list_relationships_for_entities(
            scope_a, frozenset([ea1.id])
        )

        assert len(results) == 1
        assert results[0].id == rel_a.id


# ---------------------------------------------------------------------------
# concept_map_subgraph
# ---------------------------------------------------------------------------


class TestConceptMapSubgraph:
    async def test_returns_empty_for_empty_seeds(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        entities, rels = await _repo(scope, sqlite_session).concept_map_subgraph(
            scope, frozenset(), max_nodes=50
        )
        assert entities == []
        assert rels == []

    async def test_returns_seeds_and_one_hop_neighbours(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        seed = _make_entity(scope, name="Seed")
        neighbour = _make_entity(scope, name="Neighbour")
        unrelated = _make_entity(scope, name="Unrelated")
        await repo.save_entities(scope, [seed, neighbour, unrelated])
        rel = _make_relationship(scope, seed.id, neighbour.id)
        await repo.save_relationship(scope, rel)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        entities, rels = await repo.concept_map_subgraph(
            scope, frozenset([seed.id]), max_nodes=50
        )

        entity_ids = {e.id for e in entities}
        assert seed.id in entity_ids
        assert neighbour.id in entity_ids
        assert unrelated.id not in entity_ids
        assert len(rels) == 1
        assert rels[0].id == rel.id

    async def test_caps_to_max_nodes_preserving_seeds(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        seed = _make_entity(scope, name="Seed")
        neighbours = [_make_entity(scope, name=f"N{i}") for i in range(5)]
        await repo.save_entities(scope, [seed, *neighbours])
        rels = [_make_relationship(scope, seed.id, n.id) for n in neighbours]
        await repo.save_relationships(scope, rels)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        entities, _ = await repo.concept_map_subgraph(
            scope, frozenset([seed.id]), max_nodes=3
        )

        # Total nodes capped at 3; seed is always present
        assert len(entities) == 3
        assert any(e.id == seed.id for e in entities)

    async def test_excludes_relationships_outside_cap(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        seed = _make_entity(scope, name="Seed")
        n1 = _make_entity(scope, name="N1")
        n2 = _make_entity(scope, name="N2")
        await repo.save_entities(scope, [seed, n1, n2])
        rel1 = _make_relationship(scope, seed.id, n1.id)
        rel2 = _make_relationship(scope, seed.id, n2.id)
        await repo.save_relationships(scope, [rel1, rel2])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        # Cap at 2: only seed + one neighbour fits; the relationship to the dropped
        # neighbour must also be dropped.
        entities, included_rels = await repo.concept_map_subgraph(
            scope, frozenset([seed.id]), max_nodes=2
        )

        entity_ids = {e.id for e in entities}
        for rel in included_rels:
            assert rel.source_entity_id in entity_ids
            assert rel.target_entity_id in entity_ids
