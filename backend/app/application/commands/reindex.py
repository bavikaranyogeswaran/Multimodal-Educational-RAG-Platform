"""Use case: read every document in a Knowledge Base again, under the current model.

Changing the embedding model changes what a vector means. The numbers keep the same
shape, so nothing breaks loudly — distances are still computed and results still ranked,
they just stop corresponding to similarity. Every chunk has to be read again before the
Knowledge Base can answer from the new model at all.

The rebuild writes each document at the configured index version while the Knowledge Base
goes on pointing retrieval at the old one. That ordering is the design: for as long as the
rebuild runs the new version is only half present, and answering out of a half-built index
is the failure this exists to avoid. The cost is that a document already rebuilt is not
searchable until the flip, so the Knowledge Base thins as the rebuild proceeds and is whole
again at the end — a visible cost paid deliberately in place of a silent one.

Nothing here spans one transaction. A rebuild runs for as long as it takes to read a
library, and holding that open would mean a failure hours in discarded every document that
had already worked. Each document is committed as it finishes, which is also what lets the
one being read say so: a rebuild that stops halfway leaves that document marked processing
rather than claiming to be finished with an index that has quietly gone.

Documents are read one at a time, because ingestion holds a model on the GPU and the card
has room for one.
"""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import structlog
from structlog.stdlib import BoundLogger

from app.application.commands.ingest_document import (
    IngestDocumentCommand,
    IngestDocumentUseCase,
)
from app.domain.documents.entities import Document
from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType
from app.domain.errors import InvariantViolationError
from app.domain.jobs.entities import ProcessingJob
from app.domain.ports.repositories import DocumentRepository, JobRepository, KnowledgeBaseRepository
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RebuildUnit:
    """The collaborators for one step of a rebuild, sharing one transaction."""

    knowledge_bases: KnowledgeBaseRepository
    documents: DocumentRepository
    ingest: IngestDocumentUseCase
    job_repo: JobRepository


class RebuildUnitOfWork(Protocol):
    """Opens a rebuild's collaborators over a transaction of their own.

    Built per block rather than handed in ready-made, because a rebuild is not one
    change: it is a document read, committed, and then the next. A repository received
    once would tie every document to a single transaction that stays open for hours and
    loses all of them together.
    """

    def __call__(self) -> AbstractAsyncContextManager[RebuildUnit]: ...


@dataclass(frozen=True)
class ReindexKnowledgeBaseCommand:
    scope: ScopeContext


@dataclass(frozen=True)
class ReindexResult:
    """What the rebuild did, for the caller to log and for tests to read."""

    index_version: int
    rebuilt: int
    failed: int
    #: Whether retrieval now answers from the version this rebuild wrote.
    activated: bool


class ReindexKnowledgeBaseUseCase:
    """Rebuild a Knowledge Base's index, then point retrieval at it."""

    def __init__(self, unit_of_work: RebuildUnitOfWork, *, index_version: int) -> None:
        self._unit = unit_of_work
        self._index_version = index_version

    async def execute(self, command: ReindexKnowledgeBaseCommand) -> ReindexResult:
        scope = command.scope

        async with self._unit() as work:
            kb = await work.knowledge_bases.get(scope)
            if kb is None:
                raise InvariantViolationError(f"Knowledge Base {scope.knowledge_base_id} not found")
            # Only documents that finished reading are rebuilt. One that failed has no
            # index entry to replace, and one still being read is being written by
            # another job — reading it again would put two writers on the same rows.
            documents = [
                doc
                for doc in await work.documents.list(scope)
                if doc.status is DocumentStatus.COMPLETED
            ]

        log = _log.bind(
            knowledge_base_id=str(scope.knowledge_base_id),
            index_version=self._index_version,
            documents=len(documents),
        )
        log.info("reindex_started", active_index_version=kb.active_index_version)

        rebuilt, failed = 0, 0
        for doc in documents:
            if await self._rebuild(scope, doc, log):
                rebuilt += 1
            else:
                failed += 1

        # Flipping is what makes the rebuilt documents reachable again, so it happens as
        # soon as any of them exists — the version they were written under is the only
        # place they now are. Staying on the old version would strand every document the
        # rebuild succeeded at, to preserve an index that is no longer complete either.
        #
        # Nothing rebuilt is the one case where the old version is still whole: the sweep
        # only runs once a document has been read, so a rebuild that never got that far
        # destroyed nothing. There the old version stays active and the failure is a
        # failure, rather than a Knowledge Base pointed at an empty index.
        activated = rebuilt > 0
        if activated:
            async with self._unit() as work:
                await work.knowledge_bases.save(
                    scope,
                    kb.with_active_index_version(self._index_version, now=datetime.now(UTC)),
                )

        log.info("reindex_finished", rebuilt=rebuilt, failed=failed, activated=activated)
        return ReindexResult(
            index_version=self._index_version,
            rebuilt=rebuilt,
            failed=failed,
            activated=activated,
        )

    async def _rebuild(self, scope: ScopeContext, doc: Document, log: BoundLogger) -> bool:
        """Read one document again. Returns whether it now sits in the new index."""
        processing = doc.mark_processing(now=datetime.now(UTC))

        # Committed before the reading starts, and on its own, so the document says it is
        # being processed for as long as that is true. Written in the same transaction as
        # the reading it precedes, it would only become visible once the reading was over
        # — which is exactly when it stops being true, and no help at all to anyone
        # looking at a rebuild that stopped halfway.
        async with self._unit() as work:
            await work.documents.save(scope, processing)

        try:
            async with self._unit() as work:
                result = await work.ingest.execute(
                    IngestDocumentCommand(scope=scope, document=processing)
                )
                await work.documents.save(scope, result.document)
                if result.searchable_chunk_ids:
                    await work.job_repo.save(
                        _embedding_job(scope, result.searchable_chunk_ids)
                    )
        except Exception as exc:
            # One unreadable document does not stop the rest, but it must not be left
            # looking finished: its old chunks may already be gone, and a completed
            # document with no index answers nothing and says nothing about why. Marked
            # failed, so it is out of retrieval and visible to whoever comes looking.
            log.exception("reindex_document_failed", document_id=str(processing.id))
            reason = (str(exc) or "unknown error")[:500]
            async with self._unit() as work:
                await work.documents.save(
                    scope, processing.mark_failed(reason, now=datetime.now(UTC))
                )
            return False
        return True


def _embedding_job(scope: ScopeContext, chunk_ids: tuple) -> ProcessingJob:
    now = datetime.now(UTC)
    return ProcessingJob(
        id=uuid.uuid4(),
        job_type=JobType.GENERATE_EMBEDDINGS,
        priority=JobPriority.BACKGROUND,
        status=JobStatus.PENDING,
        attempt_count=0,
        max_attempts=3,
        created_at=now,
        updated_at=now,
        payload={
            "user_id": str(scope.user_id),
            "knowledge_base_id": str(scope.knowledge_base_id),
            "chunk_ids": [str(c) for c in chunk_ids],
        },
    )
