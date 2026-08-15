# ruff: noqa: ARG001
"""Conversation and message resource endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.conversation import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
)
from app.domain.conversations.entities import Conversation, Message
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_kb_scope)],
)

_PHASE = "9"
_404_CONVERSATION = "Conversation not found"


def _conv_response(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conv.id,
        knowledge_base_id=conv.knowledge_base_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        active_document_id=conv.active_document_id,
        active_page_number=conv.active_page_number,
        active_figure_id=conv.active_figure_id,
        active_table_id=conv.active_table_id,
    )


def _msg_response(msg: Message) -> MessageResponse:
    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        status=msg.status,
        content=msg.content.value,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
        rewritten_query=msg.rewritten_query,
        model_id=msg.model_id,
        prompt_tokens=msg.prompt_tokens,
        completion_tokens=msg.completion_tokens,
        finish_reason=msg.finish_reason,
    )


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
    return _conv_response(conversation)


@router.get("", status_code=200)
async def list_conversations(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConversationResponse]:
    repo = SqlConversationRepository(scope=scope, session=session)
    conversations = await repo.list(scope)
    return [_conv_response(c) for c in conversations]


@router.get("/{conversation_id}", status_code=200)
async def get_conversation(
    conversation_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationResponse:
    repo = SqlConversationRepository(scope=scope, session=session)
    conversation = await repo.get(scope, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=_404_CONVERSATION)
    return _conv_response(conversation)


@router.post("/{conversation_id}/stream", status_code=501)
async def stream_response(conversation_id: uuid.UUID) -> dict[str, str]:
    return {"detail": "Not implemented", "phase": _PHASE}


@router.get("/{conversation_id}/messages", status_code=200)
async def list_messages(
    conversation_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[MessageResponse]:
    repo = SqlConversationRepository(scope=scope, session=session)
    conversation = await repo.get(scope, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=_404_CONVERSATION)
    messages = await repo.list_messages(scope, conversation_id, limit=limit)
    return [_msg_response(m) for m in messages]
