"""FastAPI dependency that resolves KB ownership into a ScopeContext."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.session import get_session


async def get_kb_scope(
    kb_id: uuid.UUID,
    user_id: Annotated[uuid.UUID, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScopeContext:
    """Verify KB ownership and return a ScopeContext.

    Returns 404 whether the KB does not exist or belongs to a different user.
    The two cases are indistinguishable to the caller — a scoped resource that
    another user owns must look identical to one that does not exist (FR-AUTH-13).
    """
    row = (
        await session.execute(
            select(KnowledgeBaseModel.id, KnowledgeBaseModel.user_id).where(
                KnowledgeBaseModel.id == kb_id
            )
        )
    ).one_or_none()

    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    return ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
