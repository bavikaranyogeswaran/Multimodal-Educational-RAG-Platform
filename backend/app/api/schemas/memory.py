"""Pydantic schemas for the Memory API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.memory.entities import MemoryFact


class MemoryFactResponse(BaseModel):
    id: UUID
    memory_type: MemoryType
    key: str
    value: dict[str, Any]
    confidence: float
    provenance: MemoryProvenance
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    @classmethod
    def from_domain(cls, fact: MemoryFact) -> MemoryFactResponse:
        return cls(
            id=fact.id,
            memory_type=fact.memory_type,
            key=fact.key,
            value=fact.value,
            confidence=fact.confidence,
            provenance=fact.provenance,
            status=fact.status,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            expires_at=fact.expires_at,
        )


class MemoryFactListResponse(BaseModel):
    facts: list[MemoryFactResponse]


class MemoryFactUpdateRequest(BaseModel):
    """Student-initiated update: dispute/delete a fact, or correct its value."""

    status: Literal["DISPUTED", "DELETED"] | None = None
    new_value: str | None = None

    @model_validator(mode="after")
    def _require_one(self) -> MemoryFactUpdateRequest:
        if self.status is None and self.new_value is None:
            raise ValueError("provide either 'status' or 'new_value'")
        return self


class EpisodeResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    text: str
    message_count: int
    created_at: datetime
