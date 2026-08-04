"""The Knowledge Base.

The organisational unit a student works in, and the boundary every other record is scoped
to. A Knowledge Base knows its own scope, which is why nothing else has to construct one
from loose identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID

from app.domain.enums import ExplanationLevel
from app.domain.errors import InvariantViolationError
from app.domain.invariants import (
    require_non_blank,
    require_ordered,
    require_positive,
    require_timezone_aware,
)
from app.domain.scope import ScopeContext

MAX_NAME_LENGTH = 200


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    """A subject, course or examination a student is studying for.

    The two version pointers are what allow derived data to be rebuilt without downtime.
    Retrieval pins the active index version, so a reindex can populate a new version
    alongside the old one and become visible in a single move rather than leaving the
    Knowledge Base half-searchable while it runs.
    """

    id: UUID
    user_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    description: str | None = None
    subject: str | None = None
    learning_goal: str | None = None
    preferred_language: str = "en"
    explanation_level: ExplanationLevel = ExplanationLevel.INTERMEDIATE
    exam_date: date | None = None

    #: Graph extraction runs an expensive model over every parent section, and most
    #: questions never touch the graph, so it is off unless a student asks for it.
    graph_enabled: bool = False

    active_index_version: int = 1
    active_graph_version: int = 1

    def __post_init__(self) -> None:
        require_non_blank(self.name, "KnowledgeBase.name")
        if len(self.name) > MAX_NAME_LENGTH:
            raise InvariantViolationError(
                f"KnowledgeBase.name must be at most {MAX_NAME_LENGTH} characters, "
                f"got {len(self.name)}"
            )
        require_non_blank(self.preferred_language, "KnowledgeBase.preferred_language")
        require_positive(self.active_index_version, "KnowledgeBase.active_index_version")
        require_positive(self.active_graph_version, "KnowledgeBase.active_graph_version")
        require_timezone_aware(self.created_at, "KnowledgeBase.created_at")
        require_timezone_aware(self.updated_at, "KnowledgeBase.updated_at")
        require_ordered(
            self.created_at,
            self.updated_at,
            earlier_field="created_at",
            later_field="updated_at",
        )

    @property
    def scope(self) -> ScopeContext:
        """The isolation boundary this Knowledge Base defines.

        A Knowledge Base *is* a scope, so nothing downstream has to assemble one from two
        loose identifiers and risk pairing them wrongly.
        """
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.id)

    def days_until_exam(self, today: date) -> int | None:
        """Negative once the date has passed, which study planning needs to notice."""
        return None if self.exam_date is None else (self.exam_date - today).days

    def renamed(self, name: str, *, now: datetime) -> KnowledgeBase:
        require_non_blank(name, "KnowledgeBase.name")
        return replace(self, name=name.strip(), updated_at=now)

    def with_graph_enabled(self, *, enabled: bool, now: datetime) -> KnowledgeBase:
        """Turn graph extraction on or off.

        Turning it on is what triggers a backfill over documents already ingested;
        turning it off stops new extraction but keeps whatever was built, so the decision
        is reversible without losing work.
        """
        return replace(self, graph_enabled=enabled, updated_at=now)

    def with_next_index_version(self, *, now: datetime) -> KnowledgeBase:
        """Point retrieval at a newly built embedding index.

        Called after a reindex has finished, not when it starts — the old version stays
        active for the whole rebuild.
        """
        return replace(
            self,
            active_index_version=self.active_index_version + 1,
            updated_at=now,
        )

    def with_next_graph_version(self, *, now: datetime) -> KnowledgeBase:
        return replace(
            self,
            active_graph_version=self.active_graph_version + 1,
            updated_at=now,
        )
