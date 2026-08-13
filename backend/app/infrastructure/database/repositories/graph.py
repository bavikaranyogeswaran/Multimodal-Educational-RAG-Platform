"""SQLAlchemy implementation of GraphRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.models.graph import GraphEntityModel, GraphRelationshipModel
from app.infrastructure.database.repository import ScopedRepository


class SqlGraphRepository(ScopedRepository):
    """Reads and writes GraphEntity and GraphRelationship aggregates via SQLAlchemy."""

    async def get_entity(
        self, scope: ScopeContext, entity_id: UUID
    ) -> GraphEntity | None:
        self._require_scope(scope)
        stmt = (
            select(GraphEntityModel)
            .where(
                GraphEntityModel.id == entity_id,
                self._scope_filter(GraphEntityModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _entity_to_entity(row) if row else None

    async def save_entity(self, scope: ScopeContext, entity: GraphEntity) -> None:
        self._require_scope(scope)
        await self._session.merge(_entity_to_model(entity))

    async def save_entities(
        self, scope: ScopeContext, entities: Sequence[GraphEntity]
    ) -> None:
        self._require_scope(scope)
        for entity in entities:
            await self._session.merge(_entity_to_model(entity))

    async def get_relationship(
        self, scope: ScopeContext, relationship_id: UUID
    ) -> GraphRelationship | None:
        self._require_scope(scope)
        stmt = (
            select(GraphRelationshipModel)
            .where(
                GraphRelationshipModel.id == relationship_id,
                self._scope_filter(GraphRelationshipModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _rel_to_entity(row) if row else None

    async def save_relationship(
        self, scope: ScopeContext, relationship: GraphRelationship
    ) -> None:
        self._require_scope(scope)
        await self._session.merge(_rel_to_model(relationship))

    async def save_relationships(
        self, scope: ScopeContext, relationships: Sequence[GraphRelationship]
    ) -> None:
        self._require_scope(scope)
        for rel in relationships:
            await self._session.merge(_rel_to_model(rel))

    async def delete_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> None:
        self._require_scope(scope)
        # Relationships cascade at the DB level via FK on source_entity_id and target_entity_id.
        stmt = sa_delete(GraphEntityModel).where(
            GraphEntityModel.source_document_id == document_id,
            self._scope_filter(GraphEntityModel),
        )
        await self._session.execute(stmt)


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _entity_to_entity(row: GraphEntityModel) -> GraphEntity:
    return GraphEntity(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        entity_type=GraphNodeType(row.entity_type),
        name=row.name,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        description=row.description,
        source_document_id=row.source_document_id,
        source_chunk_id=row.source_chunk_id,
        page_number=row.page_number,
    )


def _entity_to_model(entity: GraphEntity) -> GraphEntityModel:
    return GraphEntityModel(
        id=entity.id,
        user_id=entity.user_id,
        knowledge_base_id=entity.knowledge_base_id,
        entity_type=entity.entity_type.value,
        name=entity.name,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        description=entity.description,
        source_document_id=entity.source_document_id,
        source_chunk_id=entity.source_chunk_id,
        page_number=entity.page_number,
        graph_version=1,
    )


def _rel_to_entity(row: GraphRelationshipModel) -> GraphRelationship:
    return GraphRelationship(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        source_entity_id=row.source_entity_id,
        target_entity_id=row.target_entity_id,
        relationship_type=RelationshipType(row.relationship_type),
        source_chunk_id=row.source_chunk_id,
        page_number=row.page_number,
        evidence=UntrustedText(row.evidence),
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        weight=row.weight,
        extraction_confidence=row.extraction_confidence,
    )


def _rel_to_model(rel: GraphRelationship) -> GraphRelationshipModel:
    return GraphRelationshipModel(
        id=rel.id,
        user_id=rel.user_id,
        knowledge_base_id=rel.knowledge_base_id,
        source_entity_id=rel.source_entity_id,
        target_entity_id=rel.target_entity_id,
        relationship_type=rel.relationship_type.value,
        source_chunk_id=rel.source_chunk_id,
        page_number=rel.page_number,
        evidence=rel.evidence.value,
        created_at=rel.created_at,
        updated_at=rel.updated_at,
        weight=rel.weight,
        extraction_confidence=rel.extraction_confidence,
        graph_version=1,
    )
