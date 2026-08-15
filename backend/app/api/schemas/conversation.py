"""Pydantic schemas for the Conversation API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
