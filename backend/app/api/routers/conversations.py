"""Conversation and message resource endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.answer import get_answer_use_case
from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.conversation import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    StreamRequest,
)
from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.domain.conversations.entities import Conversation, Message
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_kb_scope)],
)

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
    await session.commit()
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


@router.post("/{conversation_id}/stream", status_code=200)
async def stream_response(
    conversation_id: uuid.UUID,
    body: StreamRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    use_case: Annotated[AnswerUseCase, Depends(get_answer_use_case)],
) -> StreamingResponse:
    repo = SqlConversationRepository(scope=scope, session=session)
    conversation = await repo.get(scope, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=_404_CONVERSATION)

    command = AnswerCommand(
        scope=scope,
        conversation_id=conversation_id,
        query=body.query,
    )
    stream = await use_case.execute(command)

    async def _event_stream() -> AsyncIterator[str]:
        # Closing the inner stream is what tells the use case the student has gone, and
        # it has to happen here rather than whenever the generator is collected: the turn
        # is not recorded until its cleanup runs, and a record that waits on the garbage
        # collector is a record with no guaranteed arrival time.
        try:
            async for token in stream:
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await stream.aclose()

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


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
