"""SQLAlchemy implementation of GraphRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.models.graph import GraphEntityModel, GraphRelationshipModel
from app.infrastructure.database.repository import ScopedRepository

#: How far the concept map walks from its seeds. One hop keeps a view readable and the
#: query a single join; the traversal is written as a recursive walk so raising this is
#: a change of number rather than a change of shape, if evaluation ever shows one hop
#: is not enough to answer a relationship question.
_TRAVERSAL_DEPTH = 1


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

    async def list_entities_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> list[GraphEntity]:
        self._require_scope(scope)
        stmt = (
            select(GraphEntityModel)
            .where(
                GraphEntityModel.source_document_id == document_id,
                self._scope_filter(GraphEntityModel),
            )
            .order_by(GraphEntityModel.name)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_entity_to_entity(row) for row in rows]

    async def find_entity_by_name(
        self, scope: ScopeContext, canonical_name: str
    ) -> GraphEntity | None:
        self._require_scope(scope)
        stmt = (
            select(GraphEntityModel)
            .where(
                GraphEntityModel.name == canonical_name,
                self._scope_filter(GraphEntityModel),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _entity_to_entity(row) if row else None

    async def list_relationships_for_entities(
        self, scope: ScopeContext, entity_ids: frozenset[UUID]
    ) -> list[GraphRelationship]:
        self._require_scope(scope)
        if not entity_ids:
            return []
        ids = list(entity_ids)
        stmt = (
            select(GraphRelationshipModel)
            .where(
                sa.or_(
                    GraphRelationshipModel.source_entity_id.in_(ids),
                    GraphRelationshipModel.target_entity_id.in_(ids),
                ),
                self._scope_filter(GraphRelationshipModel),
            )
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_rel_to_entity(row) for row in rows]

    async def list_relationships_of_type(
        self,
        scope: ScopeContext,
        entity_ids: frozenset[UUID],
        *,
        types: frozenset[RelationshipType],
    ) -> list[GraphRelationship]:
        """Relationships touching entity_ids whose type is one of `types`."""
        self._require_scope(scope)
        if not entity_ids or not types:
            return []
        ids = list(entity_ids)
        stmt = select(GraphRelationshipModel).where(
            sa.or_(
                GraphRelationshipModel.source_entity_id.in_(ids),
                GraphRelationshipModel.target_entity_id.in_(ids),
            ),
            GraphRelationshipModel.relationship_type.in_([t.value for t in types]),
            self._scope_filter(GraphRelationshipModel),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_rel_to_entity(row) for row in rows]

    async def list_entities_by_ids(
        self, scope: ScopeContext, entity_ids: frozenset[UUID]
    ) -> list[GraphEntity]:
        """The named entities that exist within scope, ordered by name."""
        self._require_scope(scope)
        if not entity_ids:
            return []
        stmt = (
            select(GraphEntityModel)
            .where(
                GraphEntityModel.id.in_(list(entity_ids)),
                self._scope_filter(GraphEntityModel),
            )
            .order_by(GraphEntityModel.name)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_entity_to_entity(row) for row in rows]

    async def concept_map_subgraph(
        self,
        scope: ScopeContext,
        seed_entity_ids: frozenset[UUID],
        *,
        max_nodes: int,
    ) -> tuple[list[GraphEntity], list[GraphRelationship]]:
        self._require_scope(scope)
        if not seed_entity_ids:
            return [], []
        if max_nodes < 1:
            return [], []

        capped_set = await self._bounded_node_set(seed_entity_ids, max_nodes=max_nodes)
        if not capped_set:
            return [], []

        node_ids = list(capped_set)

        entity_stmt = select(GraphEntityModel).where(
            GraphEntityModel.id.in_(node_ids),
            self._scope_filter(GraphEntityModel),
        )
        entity_rows = (await self._session.execute(entity_stmt)).scalars().all()
        entities = [_entity_to_entity(row) for row in entity_rows]

        # Only edges with both endpoints inside the view. An edge to a node the cap
        # excluded would draw as a line to nothing.
        rel_stmt = select(GraphRelationshipModel).where(
            GraphRelationshipModel.source_entity_id.in_(node_ids),
            GraphRelationshipModel.target_entity_id.in_(node_ids),
            self._scope_filter(GraphRelationshipModel),
        )
        rel_rows = (await self._session.execute(rel_stmt)).scalars().all()
        relationships = [_rel_to_entity(row) for row in rel_rows]

        return entities, relationships

    async def _bounded_node_set(
        self, seed_entity_ids: frozenset[UUID], *, max_nodes: int
    ) -> frozenset[UUID]:
        """Walk out from the seeds and return at most `max_nodes` entity ids.

        The walk and the bound both happen in the database. Reading every edge that
        touches a seed and then discarding most of them in Python would make the cost of
        a capped view depend on how well connected the seed is, which is exactly what
        the cap exists to prevent — a heavily linked concept would load thousands of rows
        to render thirty.

        Ordering by depth then id keeps two things true that the previous set-iteration
        approach did not: seeds survive the cap ahead of their neighbours, and the same
        request twice returns the same subgraph.
        """
        anchor = (
            select(
                GraphEntityModel.id.label("id"),
                sa.literal(0).label("depth"),
            )
            .where(
                GraphEntityModel.id.in_(list(seed_entity_ids)),
                self._scope_filter(GraphEntityModel),
            )
        )
        reachable = anchor.cte("reachable", recursive=True)

        # An edge is undirected for traversal: whichever endpoint is already in the set,
        # the other one is the neighbour.
        neighbour = sa.case(
            (
                GraphRelationshipModel.source_entity_id == reachable.c.id,
                GraphRelationshipModel.target_entity_id,
            ),
            else_=GraphRelationshipModel.source_entity_id,
        )
        step = (
            select(
                neighbour.label("id"),
                (reachable.c.depth + 1).label("depth"),
            )
            .select_from(reachable)
            .join(
                GraphRelationshipModel,
                sa.or_(
                    GraphRelationshipModel.source_entity_id == reachable.c.id,
                    GraphRelationshipModel.target_entity_id == reachable.c.id,
                ),
            )
            .where(
                reachable.c.depth < _TRAVERSAL_DEPTH,
                self._scope_filter(GraphRelationshipModel),
            )
        )

        # UNION rather than UNION ALL: a cycle would otherwise walk for ever, and a node
        # reachable by two paths needs counting once against the cap.
        walk = reachable.union(step)

        bounded = (
            select(walk.c.id)
            .group_by(walk.c.id)
            # A node found at two depths is kept at its shortest, so a seed that is also
            # someone's neighbour is still ordered as a seed.
            .order_by(sa.func.min(walk.c.depth), walk.c.id)
            .limit(max_nodes)
        )
        rows = (await self._session.execute(bounded)).scalars().all()
        return frozenset(rows)


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
