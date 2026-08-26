"""Pydantic schemas for the Document API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import DocumentStatus


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus
    page_count: int


class DocumentResponse(BaseModel):
    """Full document representation returned by GET /{document_id}."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    filename: str
    content_type: str
    byte_size: int
    page_count: int | None = None
    status: DocumentStatus
    title: str | None = None
    checksum: str | None = None
    language: str
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None = None


class DocumentStatusResponse(BaseModel):
    """Processing-state snapshot returned by GET /{document_id}/status."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: DocumentStatus
    page_count: int | None = None
    failure_reason: str | None = None
    updated_at: datetime


class DocumentUrlResponse(BaseModel):
    """Time-limited download URL returned by GET /{document_id}/url."""

    url: str
    expires_at: datetime


class BoundingBoxResponse(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentRegionResponse(BaseModel):
    """A table or figure bounding box the student can click to focus a question."""

    id: UUID
    region_type: str  # "table" or "figure"
    page_number: int
    bounding_box: BoundingBoxResponse
