"""Conversation and message resource endpoints."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.answer import get_answer_use_case
from app.api.dependencies.scope import get_kb_scope
from app.api.schemas.conversation import (
    BoundingBoxResponse,
    CitationResponse,
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    RetrievalSourceResponse,
    UpdateConversationRequest,
    StreamRequest,
)
from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.domain.conversations.entities import Conversation, Message
from app.infrastructure.database.models.conversation import MessageCitationModel
from app.domain.errors import GenerationRejectedError
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.session import get_session

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/knowledge-bases/{kb_id}/conversations",
    tags=["conversations"],
    dependencies=[Depends(get_kb_scope)],
)

_404_CONVERSATION = "Conversation not found"

#: Shown when the material genuinely does not cover the question. The system is working
#: correctly; the student should know the gap is in the uploaded material, not the system.
_ABSTAINED_MESSAGE = (
    "The uploaded material does not contain enough information to answer this question. "
    "Try asking something the documents cover, or upload more material."
)

#: Shown when an answer fails its grounding checks. Rejection means a citation was
#: invented or the evidence contradicts the claim, so withholding it is the system
#: working — the student is told that, rather than being left with a silent stream.
_REJECTED_MESSAGE = (
    "That answer could not be verified against your material, so it was withheld. "
    "Try rephrasing the question."
)

#: Shown when generation failed outright. Deliberately different from a rejection: nothing
#: was judged and found wanting, something broke, and telling a student their question was
#: unanswerable would be a lie about their material. Says the attempt failed and stops
#: there — what broke is in the log, and is nothing the student can act on.
_FAILED_MESSAGE = (
    "Something went wrong while answering, so this response is incomplete. "
    "Try asking again."
)


def _log_stream_failure() -> None:
    """Record a failed generation without letting the recording become the failure.

    The response is already open and half-delivered by this point, so an exception raised
    while logging would take the error event and the sentinel down with it and leave the
    student holding exactly the torn connection this reports. Logging is best-effort here
    for that reason alone; a sink that cannot write is its own problem, chased through the
    fallback line rather than through a dropped stream.
    """
    try:
        _log.error("answer_stream_failed", exc_info=True)
    except Exception:
        # The traceback itself could not be written. Say that much without it, and if even
        # that fails the sink is gone entirely and there is nowhere left to say anything.
        with contextlib.suppress(Exception):
            _log.error("answer_stream_failed", detail="traceback unloggable")


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


def _citation_response(c: MessageCitationModel) -> CitationResponse:
    has_bbox = any(
        v is not None
        for v in (c.bounding_box_x0, c.bounding_box_y0, c.bounding_box_x1, c.bounding_box_y1)
    )
    return CitationResponse(
        label=c.label,
        document_id=c.document_id,
        page_number=c.page_number,
        chunk_type=c.chunk_type,
        element_type=c.element_type,
        bounding_box=BoundingBoxResponse(
            x0=c.bounding_box_x0,  # type: ignore[arg-type]
            y0=c.bounding_box_y0,  # type: ignore[arg-type]
            x1=c.bounding_box_x1,  # type: ignore[arg-type]
            y1=c.bounding_box_y1,  # type: ignore[arg-type]
        ) if has_bbox else None,
        evidence_hash=c.evidence_hash,
    )


def _msg_response(
    msg: Message,
    citations: list[MessageCitationModel] | None = None,
) -> MessageResponse:
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
        citations=[_citation_response(c) for c in (citations or [])],
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


@router.patch("/{conversation_id}", status_code=200)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: UpdateConversationRequest,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationResponse:
    repo = SqlConversationRepository(scope=scope, session=session)
    conversation = await repo.get(scope, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=_404_CONVERSATION)
    now = datetime.now(UTC)
    if "title" in body.model_fields_set and body.title is not None:
        conversation = conversation.renamed(body.title, now=now)
    if "active_table_id" in body.model_fields_set:
        if body.active_table_id is not None:
            conversation = conversation.focus_table(body.active_table_id, now=now)
        else:
            conversation = conversation.clear_selection(now=now)
    if "active_figure_id" in body.model_fields_set:
        if body.active_figure_id is not None:
            conversation = conversation.focus_figure(body.active_figure_id, now=now)
        else:
            conversation = conversation.clear_selection(now=now)
    await repo.save(scope, conversation)
    await session.commit()
    return _conv_response(conversation)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    repo = SqlConversationRepository(scope=scope, session=session)
    conversation = await repo.get(scope, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail=_404_CONVERSATION)
    await repo.delete(scope, conversation_id)
    await session.commit()


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
            try:
                async for token in stream:
                    yield f"data: {token}\n\n"
            except GenerationRejectedError as exc:
                # Validation rejects an answer before its first token, by which point the
                # 200 and its headers have already gone out — there is no status code left
                # to fail with. Saying so on the open stream is the only way the student
                # learns why nothing arrived, instead of the connection simply dropping.
                # Abstention and rejection are different outcomes and get different messages:
                # one is about the material, the other about a quality failure.
                msg = _ABSTAINED_MESSAGE if exc.abstained else _REJECTED_MESSAGE
                yield f"event: error\ndata: {msg}\n\n"
            except Exception:
                # A generation that failed rather than one that was refused: the provider
                # died, the connection dropped, something broke. Logged in full, because a
                # failure the student is told about politely is still a failure somebody
                # has to find — reporting it must not be what makes it invisible.
                # Cancellation and generator close are deliberately not caught here: both
                # mean the student stopped listening, which is not an error to report to
                # a client that has already gone.
                _log_stream_failure()
                yield f"event: error\ndata: {_FAILED_MESSAGE}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            await stream.aclose()

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.get("/{conversation_id}/messages/{message_id}/sources", status_code=200)
async def list_message_sources(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RetrievalSourceResponse]:
    repo = SqlConversationRepository(scope=scope, session=session)
    sources = await repo.list_retrieval_sources(scope, conversation_id, message_id)
    return [
        RetrievalSourceResponse(
            document_id=row.document_id,
            document_name=row.title or row.filename,
            page_number=row.page_start,
            score=row.score,
            rank=row.rank,
            cited=cited,
        )
        for row, cited in sources
    ]


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
    # Load all citations for the conversation in one query, then index them by message.
    citation_map = await repo.list_citations_by_conversation(scope, conversation_id)
    return [_msg_response(m, citation_map.get(m.id)) for m in messages]
