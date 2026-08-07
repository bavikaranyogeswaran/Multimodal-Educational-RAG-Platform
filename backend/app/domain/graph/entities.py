"""Knowledge graph entities.

A GraphEntity is a node — a concept, chapter, figure, or other element the extraction
pipeline identified as worth linking. A GraphRelationship is a typed, directed edge
between two nodes.

The provenance invariant on GraphRelationship is structural: source_chunk_id,
page_number, and evidence are required fields with no defaults. A relationship cannot
be constructed without them, so "where did this edge come from?" is always answerable.
The database NOT NULL constraint that Phase 2 adds backs up what the type already
enforces here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.errors import InvariantViolationError
from app.domain.invariants import (
    require_non_blank,
    require_ordered,
    require_positive,
    require_timezone_aware,
    require_within,
)
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText


@dataclass(frozen=True, slots=True)
class GraphEntity:
    """A node in the knowledge graph.

    Structural nodes (KNOWLEDGE_BASE, DOCUMENT) represent objects that exist in the
    schema independently of extraction; they typically omit source references.
    Content-derived nodes (CONCEPT, FIGURE, TABLE) come from the extraction pipeline
    and carry source provenance whenever it is known.

    The source fields are optional here because the constraint depends on the
    entity_type — enforcing them universally would prevent structural nodes from
    being constructed.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    entity_type: GraphNodeType
    name: str
    created_at: datetime
    updated_at: datetime
    description: str | None = None
    source_document_id: UUID | None = None
    source_chunk_id: UUID | None = None
    page_number: int | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.name, "name")
        require_timezone_aware(self.created_at, "created_at")
        require_timezone_aware(self.updated_at, "updated_at")
        require_ordered(
            self.created_at,
            self.updated_at,
            earlier_field="created_at",
            later_field="updated_at",
        )
        if self.description is not None and not self.description.strip():
            raise InvariantViolationError("description must not be blank if set")
        if self.page_number is not None:
            require_positive(self.page_number, "page_number")

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    def renamed(self, name: str, *, now: datetime) -> GraphEntity:
        return replace(self, name=name, updated_at=now)

    def with_description(self, description: str, *, now: datetime) -> GraphEntity:
        if not description.strip():
            raise InvariantViolationError("description must not be blank")
        return replace(self, description=description, updated_at=now)


@dataclass(frozen=True, slots=True)
class GraphRelationship:
    """A typed, directed edge in the knowledge graph.

    Provenance is enforced at the type level, not by convention. The three fields
    source_chunk_id, page_number, and evidence have no defaults — they sit before
    any optional field and cannot be omitted from the constructor call. This makes
    a provenance-free edge unrepresentable in Python before it could ever reach the
    database.

    Direction matters: source_entity_id → target_entity_id. PREREQUISITE_OF(A, B)
    says A must be understood before B; reversing it would say the opposite.
    """

    id: UUID
    user_id: UUID
    knowledge_base_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: RelationshipType
    # --- provenance: all three are required, none have defaults ---
    source_chunk_id: UUID
    page_number: int
    evidence: UntrustedText
    # ---------------------------------------------------------------
    created_at: datetime
    updated_at: datetime
    weight: float = 1.0
    extraction_confidence: float | None = None

    def __post_init__(self) -> None:
        require_timezone_aware(self.created_at, "created_at")
        require_timezone_aware(self.updated_at, "updated_at")
        require_ordered(
            self.created_at,
            self.updated_at,
            earlier_field="created_at",
            later_field="updated_at",
        )
        require_positive(self.page_number, "page_number")
        if self.evidence.is_blank():
            raise InvariantViolationError("evidence must not be blank")
        if self.source_entity_id == self.target_entity_id:
            raise InvariantViolationError(
                "a relationship cannot link an entity to itself"
            )
        require_positive(self.weight, "weight")
        if self.extraction_confidence is not None:
            require_within(
                self.extraction_confidence,
                "extraction_confidence",
                low=0.0,
                high=1.0,
            )

    @property
    def scope(self) -> ScopeContext:
        return ScopeContext(user_id=self.user_id, knowledge_base_id=self.knowledge_base_id)

    def with_weight(self, weight: float, *, now: datetime) -> GraphRelationship:
        """Adjust the traversal weight after a graph algorithm has scored this edge."""
        require_positive(weight, "weight")
        return replace(self, weight=weight, updated_at=now)
