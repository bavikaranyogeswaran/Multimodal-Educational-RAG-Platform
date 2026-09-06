"""Memory resource endpoints.

Five endpoints over the student's active memory facts within a Knowledge Base:

  GET  /knowledge-bases/{kb_id}/memory
    Returns all ACTIVE facts for the current user's KB scope, ordered by
    creation time (newest first).

  PATCH /knowledge-bases/{kb_id}/memory/{memory_id}
    Accepts {"status": "DISPUTED" | "DELETED"} to apply the corresponding
    domain transition, or {"new_value": "<text>"} to supersede the fact with
    a student-corrected value.

  DELETE /knowledge-bases/{kb_id}/memory/{memory_id}
    Soft-deletes one fact. Equivalent to PATCH with status=DELETED.

  GET /knowledge-bases/{kb_id}/memory/episodes
    Returns all EPISODE-tier conversation summaries for this KB scope,
    newest first (up to 200).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.memory import (
    EpisodeResponse,
    MemoryFactListResponse,
    MemoryFactResponse,
    MemoryFactUpdateRequest,
)
from app.domain.enums import MemoryProvenance
from app.domain.errors import InvariantViolationError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation_summary import (
    SqlConversationSummaryRepository,
)
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
    """Dispute, soft-delete, or correct (supersede) a single memory fact."""
    repo = SqlMemoryRepository(scope=scope, session=session)
    fact = await repo.get(scope, memory_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Memory fact not found")

    now = datetime.now(UTC)
    try:
        if body.new_value is not None:
            retired, successor = fact.create_successor(
                successor_id=uuid.uuid4(),
                value={"text": body.new_value},
                confidence=fact.confidence,
                provenance=MemoryProvenance.USER_CORRECTION,
                now=now,
            )
            await repo.save(scope, retired)
            await repo.save(scope, successor)
            await session.commit()
            return MemoryFactResponse.from_domain(successor)

        if body.status == "DISPUTED":
            updated = fact.mark_disputed(now=now)
        else:
            updated = fact.mark_deleted(now=now)
    except InvariantViolationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await repo.save(scope, updated)
    await session.commit()
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
    await session.commit()


@router.get("/episodes", response_model=list[EpisodeResponse])
async def list_episodes(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[EpisodeResponse]:
    """Return all EPISODE-tier summaries for this KB scope, newest first."""
    repo = SqlConversationSummaryRepository(scope=scope, session=session)
    summaries = await repo.list_all(scope)
    return [
        EpisodeResponse(
            id=s.id,
            conversation_id=s.conversation_id,
            text=s.text,
            message_count=s.message_count,
            created_at=s.created_at,
        )
        for s in summaries
    ]
