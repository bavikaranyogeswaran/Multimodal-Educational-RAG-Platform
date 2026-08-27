"""Pydantic schemas for the Graph API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.graph.entities import GraphEntity, GraphRelationship


class GraphEntityResponse(BaseModel):
    id: UUID
    entity_type: GraphNodeType
    name: str
    description: str | None = None
    source_document_id: UUID | None = None
    page_number: int | None = None

    @classmethod
    def from_domain(cls, entity: GraphEntity) -> GraphEntityResponse:
        return cls(
            id=entity.id,
            entity_type=entity.entity_type,
            name=entity.name,
            description=entity.description,
            source_document_id=entity.source_document_id,
            page_number=entity.page_number,
        )


class GraphRelationshipResponse(BaseModel):
    id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: RelationshipType
    page_number: int
    evidence: str

    @classmethod
    def from_domain(cls, rel: GraphRelationship) -> GraphRelationshipResponse:
        return cls(
            id=rel.id,
            source_entity_id=rel.source_entity_id,
            target_entity_id=rel.target_entity_id,
            relationship_type=rel.relationship_type,
            page_number=rel.page_number,
            evidence=rel.evidence.value,
        )


class GraphResponse(BaseModel):
    """Concept map subgraph: a set of entity nodes and the edges between them."""

    entities: list[GraphEntityResponse]
    relationships: list[GraphRelationshipResponse]


class GraphEntityDetailResponse(BaseModel):
    """A single entity with every relationship it participates in."""

    entity: GraphEntityResponse
    relationships: list[GraphRelationshipResponse]


class PrerequisiteViewResponse(BaseModel):
    """What a concept rests on, and what rests on it.

    Both directions are returned because the edge answers two different questions and
    a view that picked one would silently be the wrong view for the other. "What do I
    need first?" reads `prerequisites`; "what does this open up?" reads `unlocks`.

    `relationships` carries the edges themselves, so every claim of dependency arrives
    with the page and the passage that asserted it. A list of names alone would be the
    model's opinion presented as fact.
    """

    entity: GraphEntityResponse
    prerequisites: list[GraphEntityResponse]
    unlocks: list[GraphEntityResponse]
    relationships: list[GraphRelationshipResponse]


class RelatedViewResponse(BaseModel):
    """Concepts sitting alongside this one rather than beneath or above it.

    Association and comparison only. Containment and explanation are structure, not
    relatedness, and mixing them here would put a chapter next to its own sections.
    """

    entity: GraphEntityResponse
    related: list[GraphEntityResponse]
    relationships: list[GraphRelationshipResponse]
