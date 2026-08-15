# ruff: noqa: ARG001
"""Conversation and message resource endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.conversation import ConversationResponse, CreateConversationRequest
from app.domain.conversations.entities import Conversation
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "9"


@router.post("", status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationResponse:
    now = datetime.now(UTC)
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        title=body.title,
        created_at=now,
        updated_at=now,
        active_document_id=body.active_document_id,
        active_page_number=body.active_page_number,
        active_figure_id=body.active_figure_id,
        active_table_id=body.active_table_id,
    )
    repo = SqlConversationRepository(scope=scope, session=session)
    await repo.save(scope, conversation)
    return ConversationResponse(
        id=conversation.id,
        knowledge_base_id=conversation.knowledge_base_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        active_document_id=conversation.active_document_id,
        active_page_number=conversation.active_page_number,
        active_figure_id=conversation.active_figure_id,
        active_table_id=conversation.active_table_id,
    )


@router.get("", status_code=501)
async def list_conversations() -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{conversation_id}", status_code=501)
async def get_conversation(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.post("/{conversation_id}/stream", status_code=501)
async def stream_response(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{conversation_id}/messages", status_code=501)
async def list_messages(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}
