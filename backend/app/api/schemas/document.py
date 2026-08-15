"""Pydantic schemas for the Document API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import DocumentStatus


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus
    page_count: int
