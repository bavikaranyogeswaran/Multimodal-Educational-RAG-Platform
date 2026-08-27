"""Memory resource endpoints.

Three endpoints over the student's active memory facts within a Knowledge Base:

  GET  /knowledge-bases/{kb_id}/memory
    Returns all ACTIVE facts for the current user's KB scope, ordered by
    creation time (newest first).

  PATCH /knowledge-bases/{kb_id}/memory/{memory_id}
    Accepts {"status": "DISPUTED" | "DELETED"} and applies the corresponding
    domain transition. Only the allowed terminal transitions are accepted —
    the client cannot freely overwrite status.

  DELETE /knowledge-bases/{kb_id}/memory/{memory_id}
    Soft-deletes one fact. Equivalent to PATCH with status=DELETED but more
    REST-conventional for a removal intent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.memory import (
    MemoryFactListResponse,
    MemoryFactResponse,
    MemoryFactUpdateRequest,
)
from app.domain.errors import InvariantViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.memory import SqlMemoryRepository
from app.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/memory",
    tags=["memory"],
    dependencies=[Depends(get_kb_scope)],
)


@router.get("", response_model=MemoryFactListResponse)
async def list_memory(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemoryFactListResponse:
    """Return all ACTIVE memory facts for this student's knowledge base."""
    repo = SqlMemoryRepository(scope=scope, session=session)
    facts = await repo.list_active(scope)
    return MemoryFactListResponse(
        facts=[MemoryFactResponse.from_domain(f) for f in facts]
    )


@router.patch("/{memory_id}", response_model=MemoryFactResponse)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryFactUpdateRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MemoryFactResponse:
    """Dispute or soft-delete a single memory fact."""
    repo = SqlMemoryRepository(scope=scope, session=session)
    fact = await repo.get(scope, memory_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Memory fact not found")

    now = datetime.now(UTC)
    try:
        if body.status == "DISPUTED":
            updated = fact.mark_disputed(now=now)
        else:
            updated = fact.mark_deleted(now=now)
    except InvariantViolationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await repo.save(scope, updated)
    return MemoryFactResponse.from_domain(updated)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Soft-delete a memory fact."""
    repo = SqlMemoryRepository(scope=scope, session=session)
    fact = await repo.get(scope, memory_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Memory fact not found")

    now = datetime.now(UTC)
    try:
        deleted = fact.mark_deleted(now=now)
    except InvariantViolationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await repo.save(scope, deleted)
