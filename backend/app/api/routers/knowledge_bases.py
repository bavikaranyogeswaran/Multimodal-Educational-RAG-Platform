"""Knowledge Base CRUD router.

Endpoints that do not reference a specific KB (POST, GET list) depend only on
the authenticated user. Endpoints that target a specific KB (GET, PATCH, DELETE)
depend on `get_kb_scope`, which verifies ownership and returns a `ScopeContext`
before the handler body runs.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.knowledge_base import (
    CreateKnowledgeBaseRequest,
    KnowledgeBaseResponse,
    UpdateKnowledgeBaseRequest,
)
from app.domain.enums import ExplanationLevel
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.repositories.knowledge_base import SqlKnowledgeBaseRepository
from app.infrastructure.database.session import get_session

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", status_code=201)
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    user_id: Annotated[UUID, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeBaseResponse:
    kb_id = uuid4()
    now = datetime.now(UTC)
    scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
    kb = KnowledgeBase(
        id=kb_id,
        user_id=user_id,
        name=body.name,
        description=body.description,
        subject=body.subject,
        learning_goal=body.learning_goal,
        preferred_language=body.preferred_language or "en",
        explanation_level=body.explanation_level or ExplanationLevel.INTERMEDIATE,
        exam_date=body.exam_date,
        created_at=now,
        updated_at=now,
    )
    repo = SqlKnowledgeBaseRepository(scope, session)
    await repo.save(scope, kb)
    await session.commit()
    return KnowledgeBaseResponse.model_validate(kb)


@router.get("")
async def list_knowledge_bases(
    user_id: Annotated[UUID, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[KnowledgeBaseResponse]:
    stmt = (
        select(KnowledgeBaseModel)
        .where(KnowledgeBaseModel.user_id == user_id)
        .order_by(KnowledgeBaseModel.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [KnowledgeBaseResponse.model_validate(row) for row in rows]


@router.get("/{kb_id}")
async def get_knowledge_base(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeBaseResponse:
    repo = SqlKnowledgeBaseRepository(scope, session)
    kb = await repo.get(scope)
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return KnowledgeBaseResponse.model_validate(kb)


@router.patch("/{kb_id}")
async def update_knowledge_base(
    body: UpdateKnowledgeBaseRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeBaseResponse:
    repo = SqlKnowledgeBaseRepository(scope, session)
    kb = await repo.get(scope)
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    updates = body.model_dump(exclude_unset=True)
    now = datetime.now(UTC)
    updated_kb = replace(kb, **{**updates, "updated_at": now})
    await repo.save(scope, updated_kb)
    await session.commit()
    return KnowledgeBaseResponse.model_validate(updated_kb)


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    repo = SqlKnowledgeBaseRepository(scope, session)
    await repo.delete(scope)
    await session.commit()
