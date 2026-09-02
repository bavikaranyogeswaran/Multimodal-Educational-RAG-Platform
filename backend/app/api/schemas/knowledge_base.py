"""Pydantic schemas for the Knowledge Base CRUD API."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ExplanationLevel


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    subject: str | None = None
    learning_goal: str | None = None
    preferred_language: str | None = None
    explanation_level: ExplanationLevel | None = None
    exam_date: date | None = None


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    subject: str | None = None
    learning_goal: str | None = None
    preferred_language: str | None = None
    explanation_level: ExplanationLevel | None = None
    exam_date: date | None = None
    graph_enabled: bool | None = None


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    description: str | None = None
    subject: str | None = None
    learning_goal: str | None = None
    preferred_language: str
    explanation_level: ExplanationLevel
    exam_date: date | None = None
    graph_enabled: bool
    active_index_version: int
    active_graph_version: int
    created_at: datetime
    updated_at: datetime


class ReindexResponse(BaseModel):
    """What was queued, and what retrieval is answering from until it finishes."""

    knowledge_base_id: UUID
    job_id: UUID
    documents: int
    #: The version retrieval still answers from. It stays this until every document has
    #: been read again, so a caller polling the Knowledge Base can see when the rebuild
    #: landed by watching this number change.
    active_index_version: int
    target_index_version: int


class BuildGraphResponse(BaseModel):
    """How many graph-build jobs were queued."""

    knowledge_base_id: UUID
    jobs_queued: int
