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


class UpdateConversationRequest(BaseModel):
    """Partial update — all fields are optional; only explicitly-provided fields are applied."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    active_table_id: UUID | None = None
    active_figure_id: UUID | None = None


class StreamRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


class BoundingBoxResponse(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class CitationResponse(BaseModel):
    """One source passage the model cited in the answer.

    Location columns are copied from the evidence at citation time rather than joined
    through the chunk, so the record stays accurate after reprocessing rewrites chunks.
    """

    label: str
    document_id: UUID
    page_number: int
    chunk_type: str
    element_type: str | None = None
    bounding_box: BoundingBoxResponse | None = None
    evidence_hash: str | None = None


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
    citations: list[CitationResponse] = []


class RetrievalSourceResponse(BaseModel):
    """One retrieved chunk shown in the sources panel after an answer."""

    document_id: UUID
    document_name: str
    page_number: int
    score: float
    rank: int
    cited: bool
