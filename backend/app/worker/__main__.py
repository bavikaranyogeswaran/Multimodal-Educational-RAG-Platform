"""Background worker — run with: python -m app.worker

One worker process claims jobs one at a time and runs whichever kind of work each one
describes. Ingestion downloads a document, parses it into pages and elements, chunks and
embeds it, and holds its lease open with a heartbeat throughout because that can take
minutes. A reindex does the same for every document in a Knowledge Base in turn, so it
takes that many times longer and holds its lease the same way. Deletion removes a file,
its cached renders and its row, which does not.

Before looking for work the worker returns anything a dead worker was holding, so a job
whose owner crashed does not sit as RUNNING for ever. On SIGTERM or SIGINT it finishes
the current job, then exits cleanly.

The heartbeat runs as a task on this same event loop, which is why the parser and the
renderer both hand their work to threads rather than doing it here.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.commands.delete_document import (
    DeleteDocumentCommand,
    DeleteDocumentUseCase,
)
from app.application.commands.ingest_document import IngestDocumentCommand, IngestDocumentUseCase
from app.application.commands.reindex import (
    RebuildUnit,
    ReindexKnowledgeBaseCommand,
    ReindexKnowledgeBaseUseCase,
)
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.configuration.wire import build_container
from app.domain.documents.chunker import Chunker
from app.domain.enums import DocumentStatus, JobStatus, JobType
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
from app.infrastructure.database.repositories.knowledge_base import (
    SqlKnowledgeBaseRepository,
)
from app.runtime import loop_factory

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Heartbeat — keeps the lease alive while ingestion runs in the background
# ---------------------------------------------------------------------------


async def _heartbeat_loop(
    session_factory: async_sessionmaker[AsyncSession],
    job: ProcessingJob,
    *,
    interval_seconds: float,
    lease_seconds: int,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        if stop.is_set():
            break
        now = datetime.now(UTC)
        job = job.heartbeat(
            lease_until=now + timedelta(seconds=lease_seconds),
            now=now,
        )
        async with session_factory() as session:
            await SqlJobRepository(session).save(job)
            await session.commit()


# ---------------------------------------------------------------------------
# Per-job handler
# ---------------------------------------------------------------------------


async def _run_job(container: Container, settings: Settings, job: ProcessingJob) -> None:
    """Run whichever kind of work this job describes."""
    if job.job_type is JobType.DELETE_DOCUMENT:
        await _run_deletion(container, job)
        return
    if job.job_type is JobType.REINDEX_KNOWLEDGE_BASE:
        await _run_reindex(container, settings, job)
        return
    await _run_ingestion(container, settings, job)


async def _run_deletion(container: Container, job: ProcessingJob) -> None:
    """Finish a deletion the API began by marking the document DELETING.

    Its own transaction, and no heartbeat: removing a file, a handful of cache keys and
    a row is short work, unlike ingestion, which can run for minutes and needs its lease
    held open the whole time.
    """
    scope = _scope_from(job)
    document_id = uuid.UUID(job.payload["document_id"])
    log = _log.bind(job_id=str(job.id), document_id=str(document_id))

    async with container.session_factory() as session:
        use_case = DeleteDocumentUseCase(
            document_repo=SqlDocumentRepository(scope, session),
            storage=container.storage,
            page_renderer=container.page_renderer,
        )
        await use_case.execute(
            DeleteDocumentCommand(
                scope=scope,
                document_id=document_id,
                storage_key=str(job.payload["storage_key"]),
            )
        )
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    log.info("document_deletion_completed")


@contextlib.asynccontextmanager
async def _leased(
    container: Container, settings: Settings, job: ProcessingJob
) -> AsyncIterator[None]:
    """Hold a job's lease open for as long as the work inside runs.

    A lease is a promise to keep going, and the reclaim pass hands a job back to the
    queue when one lapses. Work that runs for minutes has to keep saying so, or a second
    worker picks up what the first is still doing.

    The heartbeat is a task on this same event loop, which is why the parser and the
    renderer both hand their work to threads rather than doing it here.
    """
    stop = asyncio.Event()
    beat = asyncio.create_task(
        _heartbeat_loop(
            container.session_factory,
            job,
            interval_seconds=settings.job.heartbeat_interval_seconds,
            lease_seconds=settings.job.lease_seconds,
            stop=stop,
        )
    )
    try:
        yield
    finally:
        stop.set()
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


def _build_ingest(
    container: Container, settings: Settings, scope: ScopeContext, session: AsyncSession
) -> IngestDocumentUseCase:
    """The ingestion pipeline, wired from the container.

    Built here rather than in the container because it is bound to a scope and a session,
    and both change per job. A reindex builds one of these per document for the same
    reason.
    """
    return IngestDocumentUseCase(
        chunk_repo=SqlChunkRepository(scope, session),
        document_repo=SqlDocumentRepository(scope, session),
        storage=container.storage,
        embedder=container.embedder,
        parser=container.pdf_parser,
        chunker=Chunker(
            container.token_counter.count,
            target_tokens=settings.chunking.child_target_tokens,
            max_tokens=settings.chunking.child_max_tokens,
            overlap_tokens=settings.chunking.child_overlap_tokens,
            parent_target_tokens=settings.chunking.parent_target_tokens,
            parent_max_tokens=settings.chunking.parent_max_tokens,
        ),
        embedding_model_id=settings.embedding.model_id,
        index_version=settings.embedding.index_version,
        figure_cropper=container.figure_cropper,
        crops_prefix=settings.storage.crops_prefix,
        model_gateway=container.model_gateway,
    )


def _rebuild_unit_of_work(
    container: Container, settings: Settings, scope: ScopeContext
) -> Callable[[], AbstractAsyncContextManager[RebuildUnit]]:
    """Open one committed transaction per step of a rebuild.

    A rebuild is not one change but a document read, committed, and then the next. Giving
    it a single session would hold a transaction open for as long as it takes to read a
    library, and lose every document in it to one failure at the end.
    """

    @contextlib.asynccontextmanager
    async def _unit() -> AsyncIterator[RebuildUnit]:
        async with container.session_factory() as session:
            yield RebuildUnit(
                knowledge_bases=SqlKnowledgeBaseRepository(scope, session),
                documents=SqlDocumentRepository(scope, session),
                ingest=_build_ingest(container, settings, scope, session),
            )
            # Reached only when the block completed. An exception propagates through the
            # yield instead, and the session closes without committing.
            await session.commit()

    return _unit


async def _run_reindex(container: Container, settings: Settings, job: ProcessingJob) -> None:
    """Read every document in a Knowledge Base again, then point retrieval at the result.

    Runs under the same lease as an ingestion and for the same reason, only longer: this
    is one ingestion per document, in sequence.

    The job is completed in a transaction of its own, after the rebuild rather than
    around it, for the same reason the rebuild does not hold one open: by the time there
    is a result to record, the session that started the work would have been open for
    hours.
    """
    scope = _scope_from(job)
    log = _log.bind(job_id=str(job.id), knowledge_base_id=str(scope.knowledge_base_id))
    log.info("reindex_job_started")

    async with _leased(container, settings, job):
        use_case = ReindexKnowledgeBaseUseCase(
            _rebuild_unit_of_work(container, settings, scope),
            index_version=settings.embedding.index_version,
        )
        result = await use_case.execute(ReindexKnowledgeBaseCommand(scope=scope))

        async with container.session_factory() as session:
            await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
            await session.commit()

    log.info(
        "reindex_job_finished",
        rebuilt=result.rebuilt,
        failed=result.failed,
        activated=result.activated,
        index_version=result.index_version,
    )


def _scope_from(job: ProcessingJob) -> ScopeContext:
    return ScopeContext(
        user_id=uuid.UUID(job.payload["user_id"]),
        knowledge_base_id=uuid.UUID(job.payload["knowledge_base_id"]),
    )


async def _run_ingestion(container: Container, settings: Settings, job: ProcessingJob) -> None:
    now = datetime.now(UTC)
    doc_id = uuid.UUID(job.payload["document_id"])
    user_id = uuid.UUID(job.payload["user_id"])
    kb_id = uuid.UUID(job.payload["knowledge_base_id"])
    scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
    log = _log.bind(job_id=str(job.id), document_id=str(doc_id))

    # Phase 1: mark document as PROCESSING in its own committed transaction
    async with container.session_factory() as session:
        doc_repo = SqlDocumentRepository(scope, session)
        doc = await doc_repo.get(scope, doc_id)
        if doc is None:
            raise RuntimeError(f"document {doc_id} not found")
        # On a retry the document is already PROCESSING — it stays that way between
        # attempts — and marking it again would be a transition from a state to itself,
        # which the entity refuses. Nothing needs saying when nothing has changed.
        if doc.status is DocumentStatus.PROCESSING:
            processing_doc = doc
        else:
            processing_doc = doc.mark_processing(now=now)
            await doc_repo.save(scope, processing_doc)
            await session.commit()

    log.info("document_ingestion_started")

    # Phase 2: run the pipeline while the lease is held open
    async with _leased(container, settings, job), container.session_factory() as session:
        completed_doc = await _build_ingest(container, settings, scope, session).execute(
            IngestDocumentCommand(scope=scope, document=processing_doc)
        )
        await SqlDocumentRepository(scope, session).save(scope, completed_doc)
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    log.info("document_ingestion_completed")


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------


async def _main() -> None:
    settings = get_settings()
    container = build_container(settings)
    worker_id = str(uuid.uuid4())
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown.set)
    except NotImplementedError:
        # Windows: asyncio signal handlers are not implemented on this platform.
        # Fall back to the synchronous interface, which handles Ctrl-C (SIGINT)
        # but not SIGTERM, since Windows does not deliver SIGTERM to Python
        # processes the same way POSIX does.
        signal.signal(signal.SIGINT, lambda *_: shutdown.set())

    _log.info("worker_started", worker_id=worker_id)

    claimable = frozenset(
        {
            JobType.DOCUMENT_INGESTION,
            JobType.DELETE_DOCUMENT,
            JobType.REINDEX_KNOWLEDGE_BASE,
        }
    )

    while not shutdown.is_set():
        # Before looking for work, return anything a dead worker was holding. A lease is
        # a promise to keep going, refreshed while the work continues; one that lapsed
        # means whoever made it is gone, and the job would otherwise sit as RUNNING for
        # ever because no worker takes a job another appears to be doing.
        async with container.session_factory() as session:
            await SqlJobRepository(session).reclaim_expired(
                job_types=claimable,
                now=datetime.now(UTC),
                backoff_base_seconds=settings.job.backoff_base_seconds,
                backoff_max_seconds=settings.job.backoff_max_seconds,
            )
            await session.commit()

        # Claim the highest-priority claimable ingestion job
        async with container.session_factory() as session:
            job = await SqlJobRepository(session).claim_next(
                job_types=claimable,
                worker_id=worker_id,
                lease_until=datetime.now(UTC) + timedelta(seconds=settings.job.lease_seconds),
            )
            await session.commit()

        if job is None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=settings.job.poll_interval_seconds,
                )
            continue

        _log.info("job_claimed", job_id=str(job.id))

        try:
            await _run_job(container, settings, job)
        except Exception as exc:
            _log.exception("job_failed", job_id=str(job.id), error=str(exc))
            now = datetime.now(UTC)
            reason = (str(exc) or "unknown error")[:500]
            failed = job.fail(
                reason=reason,
                now=now,
                backoff_base_seconds=settings.job.backoff_base_seconds,
                backoff_max_seconds=settings.job.backoff_max_seconds,
            )
            _log.info(
                "job_failed_attempt",
                job_id=str(job.id),
                attempt=failed.attempt_count,
                max_attempts=failed.max_attempts,
                status=failed.status.value,
                retry_at=failed.scheduled_at.isoformat() if failed.scheduled_at else None,
            )
            try:
                doc_id = uuid.UUID(job.payload["document_id"])
                user_id = uuid.UUID(job.payload["user_id"])
                kb_id = uuid.UUID(job.payload["knowledge_base_id"])
                scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
                async with container.session_factory() as session:
                    # The document is only failed once there will be no further attempt.
                    # While a retry is pending it is still being processed, and saying
                    # otherwise would show a student a failure that is about to be undone.
                    # Only an ingestion failure is the document's failure. A deletion
                    # that fails leaves the document DELETING, which is absorbing and
                    # correctly so — retrieval stays blocked, and the job will be
                    # retried. Trying to mark it FAILED would be an illegal transition
                    # on top of an already failing job.
                    if (
                        failed.status is JobStatus.DEAD_LETTER
                        and job.job_type is JobType.DOCUMENT_INGESTION
                    ):
                        doc_repo = SqlDocumentRepository(scope, session)
                        doc = await doc_repo.get(scope, doc_id)
                        if doc is not None and doc.status.can_transition_to(
                            DocumentStatus.FAILED
                        ):
                            await doc_repo.save(scope, doc.mark_failed(reason, now=now))
                    await SqlJobRepository(session).save(failed)
                    await session.commit()
            except Exception as cleanup_exc:
                _log.error(
                    "job_cleanup_failed",
                    job_id=str(job.id),
                    error=str(cleanup_exc),
                )

    _log.info("worker_stopped", worker_id=worker_id)


if __name__ == "__main__":
    # The loop is chosen rather than accepted: on Windows the default one refuses to
    # carry a database connection at all. See app.runtime.
    asyncio.run(_main(), loop_factory=loop_factory())
