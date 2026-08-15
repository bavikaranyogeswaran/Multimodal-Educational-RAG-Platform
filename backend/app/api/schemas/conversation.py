"""Pydantic schemas for the Conversation API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import MessageRole, MessageStatus


class CreateConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    active_document_id: UUID | None = None
    active_page_number: int | None = None
    active_figure_id: UUID | None = None
    active_table_id: UUID | None = None


class ConversationResponse(BaseModel):
    id: UUID
    knowledge_base_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    active_document_id: UUID | None = None
    active_page_number: int | None = None
    active_figure_id: UUID | None = None
    active_table_id: UUID | None = None


class StreamRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: MessageRole
    status: MessageStatus
    content: str
    created_at: datetime
    updated_at: datetime
    rewritten_query: str | None = None
    model_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
