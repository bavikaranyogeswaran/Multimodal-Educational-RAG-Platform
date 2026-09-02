"""Use case: extract a knowledge graph from a completed document.

Operates on one document at a time — the job queue dispatches one BUILD_GRAPH
job per document rather than one per KB so the work is parallelisable and a
slow document cannot block others.

The extraction pipeline:
  1. Verify graph_enabled on the KB — if off, the job is a no-op.
  2. Verify the document is COMPLETED — only indexed content is graphed.
  3. Delete any existing graph data for the document (idempotent re-run).
  4. Load every parent chunk (the extraction unit is the parent section text).
  5. For each parent chunk, call the extraction adapter to get candidate
     entities and relationships.
  6. Resolve each candidate entity through GraphDeduplicator — the same
     concept under different capitalisations becomes one canonical node.
  7. Rebuild relationship endpoints to point at canonical entity IDs, then
     deduplicate the (source, target, type) triple within this run.
  8. Dispatch a SYNC_GRAPH_PROJECTION job (currently a no-op; retained for
     schema compatibility while a Postgres-native projection is sufficient).

A chunk that raises GraphExtractionError is logged and skipped; the job
completes over the remaining chunks rather than failing the whole document.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType
from app.domain.errors import GraphExtractionError
from app.domain.graph.deduplication import GraphDeduplicator
from app.domain.graph.entities import GraphEntity
from app.domain.jobs.entities import ProcessingJob
from app.domain.ports.adapters import GraphExtractionPort
from app.domain.ports.repositories import (
    ChunkRepository,
    DocumentRepository,
    GraphRepository,
    JobRepository,
    KnowledgeBaseRepository,
)
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 3
_SYNC_PROJECTION_MAX_ATTEMPTS = 1


@dataclass(frozen=True)
class BuildGraphCommand:
    scope: ScopeContext
    document_id: UUID


class BuildGraphUseCase:
    """Run graph extraction for one document.

    The caller (worker) is responsible for:
    - claiming the BUILD_GRAPH job before calling execute
    - marking the job COMPLETED or FAILED after execute returns or raises
    - providing an already-open database session shared across all repositories
    """

    def __init__(
        self,
        kb_repo: KnowledgeBaseRepository,
        document_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        graph_repo: GraphRepository,
        extractor: GraphExtractionPort,
        job_repo: JobRepository,
    ) -> None:
        self._kb_repo = kb_repo
        self._document_repo = document_repo
        self._chunk_repo = chunk_repo
        self._graph_repo = graph_repo
        self._extractor = extractor
        self._job_repo = job_repo

    async def execute(self, command: BuildGraphCommand) -> None:
        scope = command.scope
        now = datetime.now(UTC)

        kb = await self._kb_repo.get(scope)
        if kb is None or not kb.graph_enabled:
            _log.info(
                "build_graph.skipped",
                reason="graph disabled or KB not found",
                knowledge_base_id=str(scope.knowledge_base_id),
            )
            return

        doc = await self._document_repo.get(scope, command.document_id)
        if doc is None or doc.status is not DocumentStatus.COMPLETED:
            _log.info(
                "build_graph.skipped",
                reason="document not found or not COMPLETED",
                document_id=str(command.document_id),
            )
            return

        # Remove any graph data from a previous run before re-extracting. This
        # makes the operation idempotent: a retried job produces the same result.
        await self._graph_repo.delete_for_document(scope, command.document_id)

        all_chunks = await self._chunk_repo.list_for_document(scope, command.document_id)
        parent_chunks = [c for c in all_chunks if c.is_parent]

        if not parent_chunks:
            _log.info(
                "build_graph.no_parent_chunks",
                document_id=str(command.document_id),
            )
            await self._dispatch_sync_projection(scope, now)
            return

        dedup = GraphDeduplicator()
        entity_count = 0
        rel_count = 0

        for chunk in parent_chunks:
            try:
                candidate_entities, candidate_rels = await self._extractor.extract(
                    scope,
                    text=chunk.text.value,
                    document_id=command.document_id,
                    chunk_id=chunk.id,
                    page_number=chunk.page_start,
                )
            except GraphExtractionError:
                _log.warning(
                    "build_graph.chunk_extraction_failed",
                    chunk_id=str(chunk.id),
                    exc_info=True,
                )
                continue

            # Resolve candidates to canonical entities; track the id remapping
            # so relationships can be re-pointed at the canonical IDs.
            id_map: dict[UUID, GraphEntity] = {}
            for candidate in candidate_entities:
                canonical = await dedup.resolve_entity(scope, candidate, self._graph_repo)
                id_map[candidate.id] = canonical
            entity_count += len(id_map)

            for rel in candidate_rels:
                canonical_src = id_map.get(rel.source_entity_id)
                canonical_tgt = id_map.get(rel.target_entity_id)
                if canonical_src is None or canonical_tgt is None:
                    # Relationship references an entity that failed to resolve —
                    # skip rather than writing a dangling edge.
                    continue

                canonical_rel = replace(
                    rel,
                    source_entity_id=canonical_src.id,
                    target_entity_id=canonical_tgt.id,
                )

                resolved = dedup.resolve_relationship(canonical_rel)
                if resolved is not None:
                    await self._graph_repo.save_relationship(scope, resolved)
                    rel_count += 1

        _log.info(
            "build_graph.complete",
            document_id=str(command.document_id),
            entities=entity_count,
            relationships=rel_count,
        )

        await self._dispatch_sync_projection(scope, now)

    async def _dispatch_sync_projection(
        self, scope: ScopeContext, now: datetime
    ) -> None:
        """Dispatch the no-op SYNC_GRAPH_PROJECTION job required by the job-type enum."""
        job = ProcessingJob(
            id=uuid4(),
            job_type=JobType.SYNC_GRAPH_PROJECTION,
            priority=JobPriority.BACKGROUND,
            status=JobStatus.PENDING,
            attempt_count=0,
            max_attempts=_SYNC_PROJECTION_MAX_ATTEMPTS,
            created_at=now,
            updated_at=now,
            payload={
                "knowledge_base_id": str(scope.knowledge_base_id),
                "user_id": str(scope.user_id),
            },
        )
        await self._job_repo.save(job)
