"""Memory fact entity.

A memory fact is a durable piece of information about the student — a preference, a goal,
an identified weak topic. The key rule: when a fact is corrected, the old version is
superseded rather than overwritten. The audit chain is structural: every correction
produces two rows, one retiring the old fact and one activating the new one, and the
link between them is the superseded_by field. No service decides this — the entity does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_non_blank, require_ordered, require_timezone_aware
from app.domain.scope import ScopeContext


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """A single durable piece of information about a student within one Knowledge Base.

    Status is a lifecycle, not a free label. The transition that matters most is
    supersession: a correction produces a (retired, successor) pair returned together,
    so the caller can store both atomically.

    Every fact carries a key (the semantic identifier, e.g. "exam_date") and a
    structured value (the payload, e.g. {"date": "2026-12-01"}). The key is invariant
    across corrections — only the value, confidence, and provenance change.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    memory_type: MemoryType
    key: str
    value: dict[str, Any]
    confidence: float
    provenance: MemoryProvenance
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    valid_from: datetime
    source_message_id: UUID | None = None
    last_confirmed_at: datetime | None = None
    expires_at: datetime | None = None
    valid_until: datetime | None = None
    superseded_by: UUID | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.key, "key")
        if not 0.0 <= self.confidence <= 1.0:
            raise InvariantViolationError(
                f"confidence must be in [0.0, 1.0]; got {self.confidence}"
            )
        require_timezone_aware(self.created_at, "created_at")
        require_timezone_aware(self.updated_at, "updated_at")
        require_timezone_aware(self.valid_from, "valid_from")
        if self.valid_until is not None:
            require_timezone_aware(self.valid_until, "valid_until")
            require_ordered(
                self.valid_from,
                self.valid_until,
                earlier_field="valid_from",
                later_field="valid_until",
            )
        if self.status is MemoryStatus.SUPERSEDED and self.superseded_by is None:
            raise InvariantViolationError(
                "a superseded fact must identify its replacement via superseded_by"
            )
        if self.status is not MemoryStatus.SUPERSEDED and self.superseded_by is not None:
            raise InvariantViolationError(
                "superseded_by may only be set when status is SUPERSEDED"
            )

    @property
    def content(self) -> str:
        """Human-readable representation used for full-text search indexing."""
        return f"{self.key}: {json.dumps(self.value, ensure_ascii=False)}"

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    def create_successor(
        self,
        *,
        successor_id: UUID,
        value: dict[str, Any],
        confidence: float,
        provenance: MemoryProvenance,
        now: datetime,
    ) -> tuple[MemoryFact, MemoryFact]:
        """Return (retired, successor).

        The key is inherited from the original — corrections update the value, not the
        semantic identifier. The caller supplies the successor's id so both rows can be
        written atomically without a round-trip to discover the generated key.
        """
        if self.status is not MemoryStatus.ACTIVE:
            raise InvariantViolationError(
                f"only an active fact can have a successor; this fact is {self.status}"
            )
        if successor_id == self.id:
            raise InvariantViolationError("a fact cannot supersede itself")
        retired = replace(
            self,
            status=MemoryStatus.SUPERSEDED,
            superseded_by=successor_id,
            updated_at=now,
        )
        successor = MemoryFact(
            id=successor_id,
            user_id=self.user_id,
            knowledge_base_id=self.knowledge_base_id,
            memory_type=self.memory_type,
            key=self.key,
            value=value,
            confidence=confidence,
            provenance=provenance,
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            valid_from=now,
        )
        return retired, successor

    def mark_disputed(self, *, now: datetime) -> MemoryFact:
        """Flag the fact for review without retiring it from the active set."""
        if self.status not in {MemoryStatus.ACTIVE, MemoryStatus.UNCONFIRMED}:
            raise InvariantViolationError(
                f"cannot dispute a fact in status {self.status}"
            )
        return replace(self, status=MemoryStatus.DISPUTED, updated_at=now)

    def mark_expired(self, *, now: datetime) -> MemoryFact:
        if self.status is not MemoryStatus.ACTIVE:
            raise InvariantViolationError(
                f"only an active fact can expire; this fact is {self.status}"
            )
        return replace(self, status=MemoryStatus.EXPIRED, updated_at=now)

    def mark_deleted(self, *, now: datetime) -> MemoryFact:
        """Soft-delete — the row stays for audit; it is simply excluded from retrieval."""
        if self.status in {MemoryStatus.DELETED, MemoryStatus.SUPERSEDED}:
            raise InvariantViolationError(
                f"a {self.status} fact cannot be deleted"
            )
        return replace(self, status=MemoryStatus.DELETED, updated_at=now)
