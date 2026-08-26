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
)
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
        raise HTTPException(status_code=404, detail="Graph entity not found")

    rels = await repo.list_relationships_for_entities(
        scope, frozenset({entity_id})
    )

    return GraphEntityDetailResponse(
        entity=GraphEntityResponse.from_domain(entity),
        relationships=[GraphRelationshipResponse.from_domain(r) for r in rels],
    )
