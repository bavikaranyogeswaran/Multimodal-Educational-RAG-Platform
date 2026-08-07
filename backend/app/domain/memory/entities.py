"""Memory fact entity.

A memory fact is a durable piece of information about the student — a preference, a goal,
an identified weak topic. The key rule: when a fact is corrected, the old version is
superseded rather than overwritten. The audit chain is structural: every correction
produces two rows, one retiring the old fact and one activating the new one, and the
link between them is the superseded_by field. No service decides this — the entity does.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
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
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    memory_type: MemoryType
    content: str
    provenance: MemoryProvenance
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    valid_from: datetime
    valid_until: datetime | None = None
    superseded_by: UUID | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.content, "content")
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
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    def create_successor(
        self,
        *,
        successor_id: UUID,
        content: str,
        provenance: MemoryProvenance,
        now: datetime,
    ) -> tuple[MemoryFact, MemoryFact]:
        """Return (retired, successor).

        The caller supplies the successor's identifier so both facts can be written
        atomically without a database round-trip to discover the generated key. The
        original entity is frozen — this fact is unchanged; the returned retired copy
        is what gets persisted.
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
            content=content,
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
