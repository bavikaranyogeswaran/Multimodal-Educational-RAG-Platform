"""Graph name normalization and deduplication service.

A single extraction run over a document can produce multiple candidate entities
with spelling variations of the same concept ("Newton's Laws", "NEWTON'S LAWS").
This service normalizes names to a canonical form before any repository write,
and checks the repository for an existing entity before creating a new one.

GraphDeduplicator is stateful: it keeps an in-memory cache of what it has already
resolved in this run, so repeated encounters with the same name cost one repository
call at most. Create one instance per BUILD_GRAPH worker invocation and discard it
when the job completes.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.domain.enums import RelationshipType
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.ports.repositories import GraphRepository
from app.domain.scope import ScopeContext


def normalize_name(name: str) -> str:
    """Return the canonical form of a graph entity name.

    Case-folds (Unicode-aware lowercase), strips leading/trailing whitespace,
    and collapses internal runs of whitespace to a single space. Every entity
    write and every lookup goes through this function so the match behaviour is
    identical on both sides.
    """
    return " ".join(name.casefold().split())


class GraphDeduplicator:
    """Resolve candidate entities and relationships to their canonical forms.

    Entity deduplication:
      - The candidate name is normalized.
      - The repository is checked for an existing entity with that normalized
        name. If one exists, it is returned and the candidate is discarded.
      - If none exists, the candidate is saved under the normalized name and
        returned.
      - An in-memory cache prevents redundant repository calls for names seen
        more than once in the same run.

    Relationship deduplication:
      - The (source_entity_id, target_entity_id, relationship_type) triple is
        checked against every triple scheduled for write in this run.
      - A duplicate returns None; the caller skips it.
      - This is within-run deduplication only. Cross-run deduplication is
        handled by the BUILD_GRAPH worker deleting old data before re-extracting.
    """

    def __init__(self) -> None:
        # normalized_name → canonical GraphEntity already resolved this run
        self._entity_cache: dict[str, GraphEntity] = {}
        # (source_entity_id, target_entity_id, relationship_type) already seen
        self._seen_rels: set[tuple[UUID, UUID, RelationshipType]] = set()

    async def resolve_entity(
        self,
        scope: ScopeContext,
        candidate: GraphEntity,
        repo: GraphRepository,
    ) -> GraphEntity:
        """Return the canonical entity for this candidate, writing if necessary.

        If the cache or repository already holds an entity with the normalized
        name, that entity is returned without a write. Otherwise the candidate
        is stored under its normalized name and returned.
        """
        normalized = normalize_name(candidate.name)

        cached = self._entity_cache.get(normalized)
        if cached is not None:
            return cached

        existing = await repo.find_entity_by_name(scope, normalized)
        if existing is not None:
            self._entity_cache[normalized] = existing
            return existing

        canonical = replace(candidate, name=normalized)
        await repo.save_entity(scope, canonical)
        self._entity_cache[normalized] = canonical
        return canonical

    def resolve_relationship(
        self,
        relationship: GraphRelationship,
    ) -> GraphRelationship | None:
        """Return the relationship if it is novel, or None if it duplicates one seen this run.

        The caller must ensure that source_entity_id and target_entity_id already
        reference canonical entities (i.e. the entity has been passed through
        resolve_entity first).
        """
        key: tuple[UUID, UUID, RelationshipType] = (
            relationship.source_entity_id,
            relationship.target_entity_id,
            relationship.relationship_type,
        )
        if key in self._seen_rels:
            return None
        self._seen_rels.add(key)
        return relationship
