"""Tests for BuildGraphUseCase."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.application.commands.build_graph import BuildGraphCommand, BuildGraphUseCase
from app.domain.enums import (
    DocumentStatus,
    GraphNodeType,
    JobPriority,
    JobStatus,
    JobType,
    RelationshipType,
)
from app.domain.errors import GraphExtractionError
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _kb(*, graph_enabled: bool = True) -> MagicMock:
    kb = MagicMock()
    kb.graph_enabled = graph_enabled
    return kb


def _doc(*, status: DocumentStatus = DocumentStatus.COMPLETED) -> MagicMock:
    doc = MagicMock()
    doc.status = status
    return doc


def _chunk(
    scope: ScopeContext,
    *,
    parent: bool = True,
    text: str = "Some educational text.",
    page_start: int = 1,
    chunk_id: uuid.UUID | None = None,
) -> MagicMock:
    chunk = MagicMock()
    chunk.id = chunk_id or uuid.uuid4()
    chunk.is_parent = parent
    chunk.text = UntrustedText(text)
    chunk.page_start = page_start
    return chunk


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


def _rel(
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
        evidence=UntrustedText("A relates to B in this passage."),
        created_at=now,
        updated_at=now,
    )


def _use_case(
    kb_repo: AsyncMock | None = None,
    document_repo: AsyncMock | None = None,
    chunk_repo: AsyncMock | None = None,
    graph_repo: AsyncMock | None = None,
    extractor: AsyncMock | None = None,
    job_repo: AsyncMock | None = None,
) -> BuildGraphUseCase:
    return BuildGraphUseCase(
        kb_repo=kb_repo or AsyncMock(),
        document_repo=document_repo or AsyncMock(),
        chunk_repo=chunk_repo or AsyncMock(),
        graph_repo=graph_repo or AsyncMock(),
        extractor=extractor or AsyncMock(),
        job_repo=job_repo or AsyncMock(),
    )


def _default_repos(scope: ScopeContext, *, graph_enabled: bool = True, doc_status: DocumentStatus = DocumentStatus.COMPLETED):
    """Return mocked repositories pre-wired for the happy path."""
    kb_repo = AsyncMock()
    kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=graph_enabled))

    doc_repo = AsyncMock()
    doc_repo.get = AsyncMock(return_value=_doc(status=doc_status))

    graph_repo = AsyncMock()
    graph_repo.delete_for_document = AsyncMock(return_value=None)
    graph_repo.find_entity_by_name = AsyncMock(return_value=None)
    graph_repo.save_entity = AsyncMock(return_value=None)
    graph_repo.save_relationship = AsyncMock(return_value=None)

    job_repo = AsyncMock()
    job_repo.save = AsyncMock(return_value=None)

    return kb_repo, doc_repo, graph_repo, job_repo


# ---------------------------------------------------------------------------
# early-exit conditions
# ---------------------------------------------------------------------------


class TestEarlyExitConditions:
    async def test_no_extraction_when_graph_disabled(self) -> None:
        scope = _scope()
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=False))

        graph_repo = AsyncMock()
        chunk_repo = AsyncMock()
        extractor = AsyncMock()

        uc = _use_case(
            kb_repo=kb_repo,
            graph_repo=graph_repo,
            chunk_repo=chunk_repo,
            extractor=extractor,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.delete_for_document.assert_not_awaited()
        chunk_repo.list_for_document.assert_not_awaited()
        extractor.extract.assert_not_awaited()

    async def test_no_extraction_when_kb_not_found(self) -> None:
        scope = _scope()
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=None)
        graph_repo = AsyncMock()
        extractor = AsyncMock()

        uc = _use_case(kb_repo=kb_repo, graph_repo=graph_repo, extractor=extractor)
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.delete_for_document.assert_not_awaited()
        extractor.extract.assert_not_awaited()

    async def test_no_extraction_when_document_not_found(self) -> None:
        scope = _scope()
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=None)
        graph_repo = AsyncMock()
        extractor = AsyncMock()

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            graph_repo=graph_repo,
            extractor=extractor,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.delete_for_document.assert_not_awaited()
        extractor.extract.assert_not_awaited()

    async def test_no_extraction_when_document_not_completed(self) -> None:
        scope = _scope()
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=_doc(status=DocumentStatus.PROCESSING))
        graph_repo = AsyncMock()
        extractor = AsyncMock()

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            graph_repo=graph_repo,
            extractor=extractor,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.delete_for_document.assert_not_awaited()
        extractor.extract.assert_not_awaited()

    async def test_no_extraction_when_document_failed(self) -> None:
        scope = _scope()
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=_doc(status=DocumentStatus.FAILED))
        graph_repo = AsyncMock()
        extractor = AsyncMock()

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            graph_repo=graph_repo,
            extractor=extractor,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        extractor.extract.assert_not_awaited()


# ---------------------------------------------------------------------------
# no parent chunks
# ---------------------------------------------------------------------------


class TestNoParentChunks:
    async def test_no_extractor_call_when_all_chunks_are_children(self) -> None:
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(
            return_value=[_chunk(scope, parent=False), _chunk(scope, parent=False)]
        )
        extractor = AsyncMock()

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        extractor.extract.assert_not_awaited()

    async def test_delete_called_even_when_no_parent_chunks(self) -> None:
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[])

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        graph_repo.delete_for_document.assert_awaited_once_with(scope, doc_id)

    async def test_sync_projection_job_dispatched_even_when_no_parent_chunks(self) -> None:
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[])

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        job_repo.save.assert_awaited_once()
        saved_job = job_repo.save.call_args[0][0]
        assert saved_job.job_type == JobType.SYNC_GRAPH_PROJECTION


# ---------------------------------------------------------------------------
# happy path — extraction
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_delete_called_before_extraction(self) -> None:
        """Old graph data for the document is cleared before any new entities are written."""
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        entity_a = _entity(scope, name="Alpha")
        entity_b = _entity(scope, name="Beta")
        rel = _rel(scope, entity_a.id, entity_b.id)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])

        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([entity_a, entity_b], [rel]))

        call_order: list[str] = []
        original_delete = graph_repo.delete_for_document.side_effect

        async def _record_delete(*args, **kwargs):
            call_order.append("delete")

        async def _record_save_entity(*args, **kwargs):
            call_order.append("save_entity")

        graph_repo.delete_for_document = AsyncMock(side_effect=_record_delete)
        graph_repo.save_entity = AsyncMock(side_effect=_record_save_entity)
        graph_repo.find_entity_by_name = AsyncMock(return_value=None)
        graph_repo.save_relationship = AsyncMock(return_value=None)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        assert call_order[0] == "delete"
        assert "save_entity" in call_order

    async def test_entities_saved_with_normalized_names(self) -> None:
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        entity = _entity(scope, name="NEWTON'S LAWS")
        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])

        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([entity], []))

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        graph_repo.save_entity.assert_awaited_once()
        saved = graph_repo.save_entity.call_args[0][1]
        assert saved.name == "newton's laws"

    async def test_relationship_saved_with_canonical_entity_ids(self) -> None:
        """When pre-existing entities are found in the repo, the relationship uses
        their IDs (not the candidate IDs from the extractor)."""
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        # Extractor returns candidates with their own freshly-generated IDs.
        candidate_a = _entity(scope, name="Alpha")
        candidate_b = _entity(scope, name="Beta")
        rel = _rel(scope, candidate_a.id, candidate_b.id)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])
        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([candidate_a, candidate_b], [rel]))

        # The repo already holds canonical entities with different UUIDs.
        existing_a = _entity(scope, name="alpha", entity_id=uuid.uuid4())
        existing_b = _entity(scope, name="beta", entity_id=uuid.uuid4())

        async def _find(s, name):
            if name == "alpha":
                return existing_a
            if name == "beta":
                return existing_b
            return None

        graph_repo.find_entity_by_name = AsyncMock(side_effect=_find)
        graph_repo.save_entity = AsyncMock(return_value=None)
        graph_repo.save_relationship = AsyncMock(return_value=None)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        graph_repo.save_relationship.assert_awaited_once()
        saved_rel = graph_repo.save_relationship.call_args[0][1]
        # No new entities written — existing ones were reused.
        graph_repo.save_entity.assert_not_awaited()
        # The saved relationship must point at the pre-existing canonical IDs,
        # not the extractor's ephemeral candidate IDs.
        assert saved_rel.source_entity_id == existing_a.id
        assert saved_rel.target_entity_id == existing_b.id
        assert saved_rel.source_entity_id != candidate_a.id
        assert saved_rel.target_entity_id != candidate_b.id

    async def test_sync_projection_job_dispatched_after_extraction(self) -> None:
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])
        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([], []))

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        job_repo.save.assert_awaited_once()
        job = job_repo.save.call_args[0][0]
        assert job.job_type == JobType.SYNC_GRAPH_PROJECTION
        assert job.priority == JobPriority.BACKGROUND
        assert job.status == JobStatus.PENDING

    async def test_extractor_called_once_per_parent_chunk(self) -> None:
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunks = [_chunk(scope), _chunk(scope), _chunk(scope)]
        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=chunks)

        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([], []))

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        assert extractor.extract.await_count == 3

    async def test_child_chunks_are_skipped(self) -> None:
        """Extraction only runs on parent chunks (parent_chunk_id is None)."""
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunks = [
            _chunk(scope, parent=True),
            _chunk(scope, parent=False),
            _chunk(scope, parent=False),
        ]
        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=chunks)

        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([], []))

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        assert extractor.extract.await_count == 1


# ---------------------------------------------------------------------------
# error handling — GraphExtractionError per chunk
# ---------------------------------------------------------------------------


class TestExtractionError:
    async def test_failed_chunk_is_skipped_and_next_chunk_processed(self) -> None:
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        good_chunk = _chunk(scope, text="Good text.")
        bad_chunk = _chunk(scope, text="Broken text.")

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[bad_chunk, good_chunk])

        entity = _entity(scope, name="Concept A")

        async def _extract(scope, *, text, document_id, chunk_id, page_number):
            if chunk_id == bad_chunk.id:
                raise GraphExtractionError("malformed output")
            return [entity], []

        extractor = AsyncMock()
        extractor.extract = AsyncMock(side_effect=_extract)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        # The good chunk still produced an entity.
        graph_repo.save_entity.assert_awaited_once()

    async def test_sync_projection_dispatched_even_after_partial_failure(self) -> None:
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])

        extractor = AsyncMock()
        extractor.extract = AsyncMock(side_effect=GraphExtractionError("bad"))

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        job_repo.save.assert_awaited_once()
        job = job_repo.save.call_args[0][0]
        assert job.job_type == JobType.SYNC_GRAPH_PROJECTION

    async def test_all_chunks_fail_saves_no_entities(self) -> None:
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(
            return_value=[_chunk(scope), _chunk(scope)]
        )

        extractor = AsyncMock()
        extractor.extract = AsyncMock(side_effect=GraphExtractionError("bad"))

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.save_entity.assert_not_awaited()
        graph_repo.save_relationship.assert_not_awaited()


# ---------------------------------------------------------------------------
# deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    async def test_same_entity_name_across_two_chunks_saved_once(self) -> None:
        """The same concept appearing in two parent chunks produces one canonical entity."""
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk1 = _chunk(scope)
        chunk2 = _chunk(scope)
        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[chunk1, chunk2])

        # Both chunks yield an entity named "Momentum".
        async def _extract(scope, *, text, document_id, chunk_id, page_number):
            return [_entity(scope, name="Momentum")], []

        extractor = AsyncMock()
        extractor.extract = AsyncMock(side_effect=_extract)

        graph_repo.find_entity_by_name = AsyncMock(return_value=None)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        # The second chunk hits the in-memory cache; only one save, one find call.
        assert graph_repo.save_entity.await_count == 1
        assert graph_repo.find_entity_by_name.await_count == 1

    async def test_duplicate_relationship_triple_saved_once(self) -> None:
        """The same (source, target, type) triple produced by two chunks is deduplicated."""
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk1 = _chunk(scope)
        chunk2 = _chunk(scope)
        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[chunk1, chunk2])

        entity_a = _entity(scope, name="Alpha")
        entity_b = _entity(scope, name="Beta")

        async def _extract(scope, *, text, document_id, chunk_id, page_number):
            return (
                [entity_a, entity_b],
                [_rel(scope, entity_a.id, entity_b.id)],
            )

        extractor = AsyncMock()
        extractor.extract = AsyncMock(side_effect=_extract)
        graph_repo.find_entity_by_name = AsyncMock(return_value=None)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        assert graph_repo.save_relationship.await_count == 1

    async def test_relationship_with_unresolvable_source_is_skipped(self) -> None:
        """If a relationship's source_entity_id is not in the id_map, it is dropped."""
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])

        entity_b = _entity(scope, name="Beta")
        orphan_id = uuid.uuid4()
        rel = _rel(scope, orphan_id, entity_b.id)

        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([entity_b], [rel]))
        graph_repo.find_entity_by_name = AsyncMock(return_value=None)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.save_relationship.assert_not_awaited()

    async def test_relationship_with_unresolvable_target_is_skipped(self) -> None:
        scope = _scope()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[_chunk(scope)])

        entity_a = _entity(scope, name="Alpha")
        orphan_id = uuid.uuid4()
        rel = _rel(scope, entity_a.id, orphan_id)

        extractor = AsyncMock()
        extractor.extract = AsyncMock(return_value=([entity_a], [rel]))
        graph_repo.find_entity_by_name = AsyncMock(return_value=None)

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            extractor=extractor,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=uuid.uuid4()))

        graph_repo.save_relationship.assert_not_awaited()


# ---------------------------------------------------------------------------
# idempotency — delete_for_document called on every valid run
# ---------------------------------------------------------------------------


class TestIdempotency:
    async def test_delete_called_with_correct_document_id(self) -> None:
        scope = _scope()
        doc_id = uuid.uuid4()
        kb_repo, doc_repo, graph_repo, job_repo = _default_repos(scope)

        chunk_repo = AsyncMock()
        chunk_repo.list_for_document = AsyncMock(return_value=[])

        uc = _use_case(
            kb_repo=kb_repo,
            document_repo=doc_repo,
            chunk_repo=chunk_repo,
            graph_repo=graph_repo,
            job_repo=job_repo,
        )
        await uc.execute(BuildGraphCommand(scope=scope, document_id=doc_id))

        graph_repo.delete_for_document.assert_awaited_once_with(scope, doc_id)
