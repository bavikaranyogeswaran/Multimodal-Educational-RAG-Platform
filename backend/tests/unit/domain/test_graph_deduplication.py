"""Tests for GraphDeduplicator and normalize_name."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.graph.deduplication import GraphDeduplicator, normalize_name
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _entity(
    scope: ScopeContext,
    *,
    name: str = "Newton's Laws",
    entity_id: uuid.UUID | None = None,
) -> GraphEntity:
    now = datetime.now(UTC)
    return GraphEntity(
        id=entity_id or uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        entity_type=GraphNodeType.CONCEPT,
        name=name,
        created_at=now,
        updated_at=now,
    )


def _relationship(
    scope: ScopeContext,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    *,
    rel_type: RelationshipType = RelationshipType.RELATED_TO,
) -> GraphRelationship:
    now = datetime.now(UTC)
    return GraphRelationship(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type=rel_type,
        source_chunk_id=uuid.uuid4(),
        page_number=1,
        evidence=UntrustedText("A is related to B."),
        created_at=now,
        updated_at=now,
    )


def _repo(*, existing: GraphEntity | None = None) -> AsyncMock:
    """Mock GraphRepository with a controllable find_entity_by_name result."""
    repo = AsyncMock()
    repo.find_entity_by_name = AsyncMock(return_value=existing)
    repo.save_entity = AsyncMock(return_value=None)
    return repo


# ---------------------------------------------------------------------------
# normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_lowercases(self) -> None:
        assert normalize_name("Newton's Laws") == "newton's laws"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert normalize_name("  Momentum  ") == "momentum"

    def test_collapses_internal_whitespace(self) -> None:
        assert normalize_name("kinetic   energy") == "kinetic energy"

    def test_unicode_casefold(self) -> None:
        assert normalize_name("Straße") == "strasse"

    def test_already_normalized_is_idempotent(self) -> None:
        assert normalize_name("momentum") == "momentum"

    def test_tab_counts_as_whitespace(self) -> None:
        assert normalize_name("wave\tfunction") == "wave function"

    def test_newline_counts_as_whitespace(self) -> None:
        assert normalize_name("wave\nfunction") == "wave function"


# ---------------------------------------------------------------------------
# resolve_entity — happy path
# ---------------------------------------------------------------------------


class TestResolveEntityHappyPath:
    async def test_saves_candidate_when_no_existing_entity(self) -> None:
        scope = _scope()
        candidate = _entity(scope)
        repo = _repo(existing=None)

        result = await GraphDeduplicator().resolve_entity(scope, candidate, repo)

        repo.save_entity.assert_awaited_once()
        assert result.name == normalize_name(candidate.name)

    async def test_stored_name_is_normalized(self) -> None:
        scope = _scope()
        candidate = _entity(scope, name="NEWTON'S LAWS")
        repo = _repo(existing=None)

        result = await GraphDeduplicator().resolve_entity(scope, candidate, repo)

        assert result.name == "newton's laws"
        saved_entity = repo.save_entity.call_args[0][1]
        assert saved_entity.name == "newton's laws"

    async def test_returns_existing_entity_from_repo_without_write(self) -> None:
        scope = _scope()
        existing_id = uuid.uuid4()
        existing = _entity(scope, name="newton's laws", entity_id=existing_id)
        candidate = _entity(scope, name="Newton's Laws")
        repo = _repo(existing=existing)

        result = await GraphDeduplicator().resolve_entity(scope, candidate, repo)

        repo.save_entity.assert_not_awaited()
        assert result.id == existing_id

    async def test_cache_prevents_second_repo_call_for_same_name(self) -> None:
        scope = _scope()
        candidate = _entity(scope, name="Momentum")
        repo = _repo(existing=None)
        dedup = GraphDeduplicator()

        first = await dedup.resolve_entity(scope, candidate, repo)
        second = await dedup.resolve_entity(scope, _entity(scope, name="momentum"), repo)

        assert repo.find_entity_by_name.await_count == 1
        assert first.id == second.id

    async def test_cache_hit_returns_same_entity_object(self) -> None:
        scope = _scope()
        candidate = _entity(scope, name="Entropy")
        repo = _repo(existing=None)
        dedup = GraphDeduplicator()

        first = await dedup.resolve_entity(scope, candidate, repo)
        # Variant spelling, same normalized name
        second = await dedup.resolve_entity(scope, _entity(scope, name=" ENTROPY "), repo)

        assert first is second

    async def test_two_distinct_names_resolve_independently(self) -> None:
        scope = _scope()
        repo = _repo(existing=None)
        dedup = GraphDeduplicator()

        a = await dedup.resolve_entity(scope, _entity(scope, name="Alpha"), repo)
        b = await dedup.resolve_entity(scope, _entity(scope, name="Beta"), repo)

        assert a.id != b.id
        assert repo.save_entity.await_count == 2

    async def test_preserved_fields_other_than_name(self) -> None:
        scope = _scope()
        original_id = uuid.uuid4()
        candidate = _entity(scope, name="Wave Function", entity_id=original_id)
        repo = _repo(existing=None)

        result = await GraphDeduplicator().resolve_entity(scope, candidate, repo)

        assert result.id == original_id
        assert result.entity_type == GraphNodeType.CONCEPT
        assert result.user_id == scope.user_id
        assert result.knowledge_base_id == scope.knowledge_base_id


# ---------------------------------------------------------------------------
# resolve_entity — normalization variants reach the same canonical entity
# ---------------------------------------------------------------------------


class TestNormalizationVariants:
    @pytest.mark.parametrize("variant", [
        "Newton's Laws",
        "NEWTON'S LAWS",
        "newton's laws",
        "  newton's laws  ",
        "Newton's   Laws",
    ])
    async def test_all_variants_resolve_to_same_entity(self, variant: str) -> None:
        scope = _scope()
        repo = _repo(existing=None)
        dedup = GraphDeduplicator()

        # Establish a canonical entity under the normalized form.
        first = await dedup.resolve_entity(scope, _entity(scope, name="Newton's Laws"), repo)
        result = await dedup.resolve_entity(scope, _entity(scope, name=variant), repo)

        assert result.id == first.id
        # Only one save — the first call
        assert repo.save_entity.await_count == 1


# ---------------------------------------------------------------------------
# resolve_relationship
# ---------------------------------------------------------------------------


class TestResolveRelationship:
    def test_returns_relationship_on_first_call(self) -> None:
        scope = _scope()
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        rel = _relationship(scope, src_id, tgt_id)

        result = GraphDeduplicator().resolve_relationship(rel)

        assert result is rel

    def test_returns_none_for_duplicate_triple(self) -> None:
        scope = _scope()
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        rel = _relationship(scope, src_id, tgt_id)
        dedup = GraphDeduplicator()

        first = dedup.resolve_relationship(rel)
        second = dedup.resolve_relationship(
            _relationship(scope, src_id, tgt_id)
        )

        assert first is not None
        assert second is None

    def test_different_type_same_endpoints_is_not_duplicate(self) -> None:
        scope = _scope()
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        dedup = GraphDeduplicator()

        r1 = _relationship(scope, src_id, tgt_id, rel_type=RelationshipType.RELATED_TO)
        r2 = _relationship(scope, src_id, tgt_id, rel_type=RelationshipType.PREREQUISITE_OF)

        assert dedup.resolve_relationship(r1) is not None
        assert dedup.resolve_relationship(r2) is not None

    def test_reversed_direction_is_not_duplicate(self) -> None:
        scope = _scope()
        a, b = uuid.uuid4(), uuid.uuid4()
        dedup = GraphDeduplicator()

        forward = _relationship(scope, a, b)
        backward = _relationship(scope, b, a)

        assert dedup.resolve_relationship(forward) is not None
        assert dedup.resolve_relationship(backward) is not None

    def test_multiple_unique_relationships_all_returned(self) -> None:
        scope = _scope()
        ids = [uuid.uuid4() for _ in range(3)]
        dedup = GraphDeduplicator()

        rels = [
            _relationship(scope, ids[0], ids[1]),
            _relationship(scope, ids[1], ids[2]),
            _relationship(scope, ids[0], ids[2]),
        ]

        results = [dedup.resolve_relationship(r) for r in rels]
        assert all(r is not None for r in results)

    def test_third_duplicate_also_returns_none(self) -> None:
        scope = _scope()
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()
        dedup = GraphDeduplicator()

        dedup.resolve_relationship(_relationship(scope, src_id, tgt_id))
        dedup.resolve_relationship(_relationship(scope, src_id, tgt_id))
        third = dedup.resolve_relationship(_relationship(scope, src_id, tgt_id))

        assert third is None


# ---------------------------------------------------------------------------
# isolation between deduplicator instances
# ---------------------------------------------------------------------------


class TestInstanceIsolation:
    async def test_two_instances_do_not_share_entity_cache(self) -> None:
        scope = _scope()
        repo = _repo(existing=None)

        a = await GraphDeduplicator().resolve_entity(scope, _entity(scope, name="Alpha"), repo)
        b = await GraphDeduplicator().resolve_entity(scope, _entity(scope, name="Alpha"), repo)

        # Each instance is a fresh run; both write
        assert repo.save_entity.await_count == 2
        assert a.id != b.id

    def test_two_instances_do_not_share_relationship_cache(self) -> None:
        scope = _scope()
        src_id, tgt_id = uuid.uuid4(), uuid.uuid4()

        dedup_a = GraphDeduplicator()
        dedup_b = GraphDeduplicator()

        rel = _relationship(scope, src_id, tgt_id)
        dedup_a.resolve_relationship(rel)

        assert dedup_b.resolve_relationship(rel) is not None
