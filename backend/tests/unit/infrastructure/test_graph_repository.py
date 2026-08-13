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
