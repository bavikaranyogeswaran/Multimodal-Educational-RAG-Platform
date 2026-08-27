"""Graph resource endpoints.

Two endpoints covering the concept-map surface of the knowledge graph:

  GET /graph?document_id={uuid}&max_nodes=30
    Returns the concept-map subgraph seeded by every entity extracted from the
    given document (one-hop expansion, capped at max_nodes). Without a
    document_id the graph has no seed and the response is an empty concept map.

  GET /graph/entities/{entity_id}
    Returns one entity and all relationships it participates in as source or
    target.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.graph import (
    GraphEntityDetailResponse,
    GraphEntityResponse,
    GraphRelationshipResponse,
    GraphResponse,
    PrerequisiteViewResponse,
    RelatedViewResponse,
)
from app.domain.enums import RelationshipType
from app.domain.graph.entities import GraphEntity
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.graph import SqlGraphRepository
from app.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/graph",
    tags=["graph"],
    dependencies=[Depends(get_kb_scope)],
)

_MAX_NODES_DEFAULT = 30
_MAX_NODES_UPPER = 200

_ENTITY_NOT_FOUND = "Graph entity not found"

#: What "related" means here. Association and comparison sit two concepts side by side;
#: containment and explanation describe structure, and putting a chapter in the same
#: list as its own sections would read as a peer relationship it is not.
_RELATED_TYPES = frozenset({RelationshipType.RELATED_TO, RelationshipType.COMPARES_WITH})


@router.get("", response_model=GraphResponse)
async def get_graph(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    document_id: Annotated[uuid.UUID | None, Query()] = None,
    max_nodes: Annotated[
        int, Query(ge=1, le=_MAX_NODES_UPPER)
    ] = _MAX_NODES_DEFAULT,
) -> GraphResponse:
    """Concept-map subgraph for a document, or an empty graph when no seed is given."""
    repo = SqlGraphRepository(scope, session)

    if document_id is None:
        return GraphResponse(entities=[], relationships=[])

    seed_entities = await repo.list_entities_for_document(scope, document_id)
    if not seed_entities:
        return GraphResponse(entities=[], relationships=[])

    seed_ids = frozenset(e.id for e in seed_entities)
    entities, rels = await repo.concept_map_subgraph(
        scope, seed_ids, max_nodes=max_nodes
    )

    return GraphResponse(
        entities=[GraphEntityResponse.from_domain(e) for e in entities],
        relationships=[GraphRelationshipResponse.from_domain(r) for r in rels],
    )


@router.get("/entities/{entity_id}", response_model=GraphEntityDetailResponse)
async def get_graph_entity(
    entity_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GraphEntityDetailResponse:
    """One entity and every relationship it participates in."""
    repo = SqlGraphRepository(scope, session)

    entity = await repo.get_entity(scope, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=_ENTITY_NOT_FOUND)

    rels = await repo.list_relationships_for_entities(
        scope, frozenset({entity_id})
    )

    return GraphEntityDetailResponse(
        entity=GraphEntityResponse.from_domain(entity),
        relationships=[GraphRelationshipResponse.from_domain(r) for r in rels],
    )


@router.get(
    "/entities/{entity_id}/prerequisites", response_model=PrerequisiteViewResponse
)
async def get_entity_prerequisites(
    entity_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PrerequisiteViewResponse:
    """What this concept depends on, and what depends on it.

    The edge direction carries the meaning: `A PREREQUISITE_OF B` puts A before B. So
    the prerequisites of this entity are the edges pointing at it, and the concepts it
    unlocks are the edges leaving it.
    """
    repo = SqlGraphRepository(scope, session)

    entity = await repo.get_entity(scope, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=_ENTITY_NOT_FOUND)

    rels = await repo.list_relationships_of_type(
        scope,
        frozenset({entity_id}),
        types=frozenset({RelationshipType.PREREQUISITE_OF}),
    )

    prerequisite_ids = frozenset(
        r.source_entity_id for r in rels if r.target_entity_id == entity_id
    )
    unlocked_ids = frozenset(
        r.target_entity_id for r in rels if r.source_entity_id == entity_id
    )

    neighbours = await repo.list_entities_by_ids(
        scope, prerequisite_ids | unlocked_ids
    )
    by_id = {e.id: e for e in neighbours}

    return PrerequisiteViewResponse(
        entity=GraphEntityResponse.from_domain(entity),
        prerequisites=[
            GraphEntityResponse.from_domain(by_id[i])
            for i in _ordered(prerequisite_ids, by_id)
        ],
        unlocks=[
            GraphEntityResponse.from_domain(by_id[i])
            for i in _ordered(unlocked_ids, by_id)
        ],
        relationships=[GraphRelationshipResponse.from_domain(r) for r in rels],
    )


@router.get("/entities/{entity_id}/related", response_model=RelatedViewResponse)
async def get_entity_related(
    entity_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RelatedViewResponse:
    """Concepts associated with this one, in either direction.

    Association reads the same both ways, so unlike the prerequisite view this one does
    not split by direction — it reports the other endpoint whichever end the edge
    started from.
    """
    repo = SqlGraphRepository(scope, session)

    entity = await repo.get_entity(scope, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=_ENTITY_NOT_FOUND)

    rels = await repo.list_relationships_of_type(
        scope, frozenset({entity_id}), types=_RELATED_TYPES
    )

    # Every edge here touches this entity, so the opposite endpoint is the neighbour.
    # No need to exclude the subject: a relationship linking an entity to itself cannot
    # be constructed, so one can never arrive here to be filtered out.
    related_ids = frozenset(
        r.target_entity_id if r.source_entity_id == entity_id else r.source_entity_id
        for r in rels
    )

    neighbours = await repo.list_entities_by_ids(scope, related_ids)

    return RelatedViewResponse(
        entity=GraphEntityResponse.from_domain(entity),
        related=[GraphEntityResponse.from_domain(e) for e in neighbours],
        relationships=[GraphRelationshipResponse.from_domain(r) for r in rels],
    )


def _ordered(
    ids: frozenset[uuid.UUID], by_id: dict[uuid.UUID, GraphEntity]
) -> list[uuid.UUID]:
    """Ids that resolved to an entity, in the repository's name order.

    Iterating the loaded entities rather than the id set is what supplies the order —
    the repository sorted them by name, and a set has no order to offer. It also drops
    an id that resolved to nothing, which happens when the graph is rebuilt between the
    two reads; the alternative is rendering a node with no name.
    """
    return [entity_id for entity_id in by_id if entity_id in ids]
