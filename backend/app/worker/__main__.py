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

from app.application.commands.build_graph import BuildGraphCommand, BuildGraphUseCase
from app.application.commands.compact_memory import CompactMemoryCommand, CompactMemoryUseCase
from app.application.commands.delete_document import (
    DeleteDocumentCommand,
    DeleteDocumentUseCase,
)
from app.application.commands.embed_chunks import EmbedChunksCommand, EmbedChunksUseCase
from app.application.commands.ingest_document import IngestDocumentCommand, IngestDocumentUseCase
from app.application.commands.ocr_page import OcrPageCommand, OcrPageUseCase
from app.application.commands.reindex import (
    RebuildUnit,
    ReindexKnowledgeBaseCommand,
    ReindexKnowledgeBaseUseCase,
)
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.configuration.wire import build_container
from app.domain.documents.chunker import Chunker
from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.database.repositories.conversation import SqlConversationRepository
from app.infrastructure.database.repositories.conversation_summary import SqlConversationSummaryRepository
from app.infrastructure.database.repositories.conversation_summary import SqlConversationSummaryRepository
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.graph import SqlGraphRepository
from app.infrastructure.database.repositories.job import SqlJobRepository
from app.infrastructure.database.repositories.knowledge_base import (
    SqlKnowledgeBaseRepository,
)
from app.infrastructure.graph.extractor import LlmGraphExtractor
from app.runtime import loop_factory

_log = structlog.get_logger(__name__)

#: Graph extraction is a long chain of model calls, and a transient provider failure
#: partway through is the ordinary case rather than the exceptional one. The use case
#: deletes the document's existing graph before re-extracting, so a retry rebuilds
#: cleanly instead of doubling what a half-finished attempt already wrote.
_GRAPH_BUILD_MAX_ATTEMPTS = 3


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
    if job.job_type is JobType.BUILD_GRAPH:
        await _run_build_graph(container, settings, job)
        return
    if job.job_type is JobType.SYNC_GRAPH_PROJECTION:
        await _run_sync_graph_projection(container, job)
        return
    if job.job_type is JobType.GENERATE_EMBEDDINGS:
        await _run_embed_chunks(container, settings, job)
        return
    if job.job_type is JobType.COMPACT_MEMORY:
        await _run_compact_memory(container, settings, job)
        return
    if job.job_type is JobType.OCR_PAGE:
        await _run_ocr_page(container, job)
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


async def _run_build_graph(
    container: Container, settings: Settings, job: ProcessingJob
) -> None:
    """Extract the concept graph for one completed document.

    Leased like ingestion rather than run bare: extraction calls the model once per
    parent section, so a textbook chapter is minutes of work and a lease that lapsed
    partway would hand the same document to a second worker.

    The use case decides whether there is anything to do — it returns early when the
    Knowledge Base has graphing switched off or the document never finished ingesting.
    Checking here as well would put the same rule in two places.
    """
    scope = _scope_from(job)
    document_id = uuid.UUID(job.payload["document_id"])
    log = _log.bind(job_id=str(job.id), document_id=str(document_id))

    log.info("graph_build_started")

    async with _leased(container, settings, job), container.session_factory() as session:
        use_case = BuildGraphUseCase(
            kb_repo=SqlKnowledgeBaseRepository(scope, session),
            document_repo=SqlDocumentRepository(scope, session),
            chunk_repo=SqlChunkRepository(scope, session),
            graph_repo=SqlGraphRepository(scope, session),
            extractor=LlmGraphExtractor(container.model_gateway),
            job_repo=SqlJobRepository(session),
        )
        await use_case.execute(BuildGraphCommand(scope=scope, document_id=document_id))
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    log.info("graph_build_completed")


async def _run_sync_graph_projection(container: Container, job: ProcessingJob) -> None:
    """Complete the projection job without doing anything, which is the whole design.

    The graph lives in PostgreSQL alongside everything else, so there is no second store
    to synchronise. The job type is kept because the specification names it and because
    a projection into a graph database is the documented escape hatch if one hop stops
    being enough. Claiming and completing it is what stops it accumulating as PENDING
    rows that look like a backlog.
    """
    async with container.session_factory() as session:
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    _log.info("graph_projection_noop", job_id=str(job.id))


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
        parser=container.pdf_parser,
        chunker=Chunker(
            container.token_counter.count,
            target_tokens=settings.chunking.child_target_tokens,
            max_tokens=settings.chunking.child_max_tokens,
            overlap_tokens=settings.chunking.child_overlap_tokens,
            parent_target_tokens=settings.chunking.parent_target_tokens,
            parent_max_tokens=settings.chunking.parent_max_tokens,
        ),
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
                job_repo=SqlJobRepository(session),
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
        result = await _build_ingest(container, settings, scope, session).execute(
            IngestDocumentCommand(scope=scope, document=processing_doc)
        )
        await SqlDocumentRepository(scope, session).save(scope, result.document)
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        queued_embed = await _enqueue_embed_chunks(
            scope, session, result.searchable_chunk_ids, now=datetime.now(UTC)
        )
        queued_graph = await _enqueue_graph_build(scope, session, doc_id, now=datetime.now(UTC))
        queued_ocr = await _enqueue_ocr_pages(scope, session, doc_id, now=datetime.now(UTC))
        await session.commit()

    log.info(
        "document_ingestion_completed",
        embed_job_queued=queued_embed,
        graph_build_queued=queued_graph,
        ocr_pages_queued=queued_ocr,
    )


async def _enqueue_embed_chunks(
    scope: ScopeContext,
    session: AsyncSession,
    chunk_ids: tuple[uuid.UUID, ...],
    *,
    now: datetime,
) -> bool:
    """Queue embedding for the child chunks written by an ingestion or reindex run.

    Enqueued in the transaction that completes the document, so the chunk rows and the
    embedding job are always consistent: if the transaction rolls back, the job disappears
    with the chunks it would have embedded.

    Returns False when there are no searchable chunks (a fully scanned document with no
    text), in which case no job is queued.
    """
    if not chunk_ids:
        return False

    settings = get_settings()
    await SqlJobRepository(session).save(
        ProcessingJob(
            id=uuid.uuid4(),
            job_type=JobType.GENERATE_EMBEDDINGS,
            priority=JobPriority.INTERACTIVE,
            status=JobStatus.PENDING,
            attempt_count=0,
            max_attempts=3,
            created_at=now,
            updated_at=now,
            payload={
                "user_id": str(scope.user_id),
                "knowledge_base_id": str(scope.knowledge_base_id),
                "chunk_ids": [str(c) for c in chunk_ids],
                "embedding_model_id": settings.embedding.model_id,
                "index_version": settings.embedding.index_version,
            },
        )
    )
    return True


async def _run_embed_chunks(
    container: Container, settings: Settings, job: ProcessingJob
) -> None:
    """Embed the child chunks that an ingestion job wrote without vectors."""
    scope = _scope_from(job)
    chunk_ids = tuple(
        uuid.UUID(c) for c in job.payload.get("chunk_ids", [])
    )
    embedding_model_id = str(
        job.payload.get("embedding_model_id", settings.embedding.model_id)
    )
    index_version = int(
        job.payload.get("index_version", settings.embedding.index_version)
    )
    log = _log.bind(job_id=str(job.id), chunk_count=len(chunk_ids))
    log.info("embed_chunks_started")

    async with container.session_factory() as session:
        use_case = EmbedChunksUseCase(
            chunk_repo=SqlChunkRepository(scope, session),
            embedder=container.embedder,
        )
        result = await use_case.execute(
            EmbedChunksCommand(
                scope=scope,
                chunk_ids=chunk_ids,
                embedding_model_id=embedding_model_id,
                index_version=index_version,
            )
        )
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    log.info("embed_chunks_completed", embedded=result.embedded)


async def _enqueue_ocr_pages(
    scope: ScopeContext,
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    now: datetime,
) -> int:
    """Queue one OCR job per page that the parser flagged as needing recognition.

    Enqueued inside the transaction that completes ingestion so the page rows and
    the OCR jobs are always consistent: a rolled-back ingestion leaves no orphan jobs.

    Returns the number of jobs queued (zero for fully native-text documents).
    """
    from app.infrastructure.database.repositories.document import SqlDocumentRepository

    pages = await SqlDocumentRepository(scope, session).get_pages(scope, document_id)
    ocr_pages = [p for p in pages if p.needs_ocr]

    job_repo = SqlJobRepository(session)
    for page in ocr_pages:
        await job_repo.save(
            ProcessingJob(
                id=uuid.uuid4(),
                job_type=JobType.OCR_PAGE,
                priority=JobPriority.BACKGROUND,
                status=JobStatus.PENDING,
                attempt_count=0,
                max_attempts=3,
                created_at=now,
                updated_at=now,
                payload={
                    "user_id": str(scope.user_id),
                    "knowledge_base_id": str(scope.knowledge_base_id),
                    "document_id": str(document_id),
                    "page_number": page.page_number,
                },
            )
        )
    return len(ocr_pages)


async def _run_ocr_page(container: Container, job: ProcessingJob) -> None:
    """Recognise text on one scanned or image-heavy page and persist the elements."""
    scope = _scope_from(job)
    document_id = uuid.UUID(job.payload["document_id"])
    page_number = int(job.payload["page_number"])
    log = _log.bind(
        job_id=str(job.id),
        document_id=str(document_id),
        page_number=page_number,
    )
    log.info("ocr_page_started")

    async with container.session_factory() as session:
        use_case = OcrPageUseCase(
            document_repo=SqlDocumentRepository(scope, session),
            storage=container.storage,
            page_renderer=container.page_renderer,
            ocr=container.ocr,
        )
        result = await use_case.execute(
            OcrPageCommand(
                scope=scope,
                document_id=document_id,
                page_number=page_number,
            )
        )
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    log.info("ocr_page_completed", elements_saved=result.elements_saved)


async def _run_compact_memory(
    container: Container, settings: Settings, job: ProcessingJob
) -> None:
    """Summarize a conversation's history into a rolling summary.

    Runs only when the summarizer adapter is wired. If it is absent, the job is
    marked complete immediately so it does not retry for ever on every poll cycle.
    """
    scope = _scope_from(job)
    conversation_id = uuid.UUID(job.payload["conversation_id"])
    log = _log.bind(job_id=str(job.id), conversation_id=str(conversation_id))

    summarizer = container.summarizer
    if summarizer is None:
        log.warning("compact_memory.skipped", reason="summarizer not configured")
        async with container.session_factory() as session:
            await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
            await session.commit()
        return

    log.info("compact_memory_started")
    async with container.session_factory() as session:
        use_case = CompactMemoryUseCase(
            conversation_repo=SqlConversationRepository(scope=scope, session=session),
            summarizer=summarizer,
            min_messages=settings.memory.compaction_unsummarized_messages,
            summary_repo=SqlConversationSummaryRepository(scope=scope, session=session),
        )
        result = await use_case.execute(
            CompactMemoryCommand(scope=scope, conversation_id=conversation_id)
        )
        await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
        await session.commit()

    log.info(
        "compact_memory_completed",
        summary_written=result.summary_written,
        episode_written=result.episode_summary_id is not None,
    )

    if (
        result.episode_summary_id is not None
        and result.episode_summary_text is not None
        and container.embedder is not None
    ):
        embedding = await container.embedder.embed_query(result.episode_summary_text)
        async with container.session_factory() as embed_session:
            await SqlConversationSummaryRepository(
                scope=scope, session=embed_session
            ).save_embedding(scope, result.episode_summary_id, embedding)
            await embed_session.commit()
        log.info("compact_memory_episode_embedded", episode_id=str(result.episode_summary_id))


async def _enqueue_graph_build(
    scope: ScopeContext,
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    now: datetime,
) -> bool:
    """Queue graph extraction for a document that has just finished ingesting.

    Enqueued in the transaction that completes the document, so the two cannot disagree:
    a document that reports itself indexed always has its graph job waiting, and one
    whose ingestion rolled back never leaves an orphan job pointing at content that was
    never written.

    Graphing is opt-in per Knowledge Base because extraction costs a model call per
    parent section — hundreds for a textbook. A Knowledge Base that never asked for a
    concept graph should not pay for one, so the flag is read here rather than queueing
    unconditionally and discovering the answer in the worker.
    """
    kb = await SqlKnowledgeBaseRepository(scope, session).get(scope)
    if kb is None or not kb.graph_enabled:
        return False

    await SqlJobRepository(session).save(
        ProcessingJob(
            id=uuid.uuid4(),
            job_type=JobType.BUILD_GRAPH,
            # Behind anything a student is waiting on. Nothing reads the graph until it
            # exists, and a missing graph degrades an answer rather than breaking it.
            priority=JobPriority.BACKGROUND,
            status=JobStatus.PENDING,
            attempt_count=0,
            max_attempts=_GRAPH_BUILD_MAX_ATTEMPTS,
            created_at=now,
            updated_at=now,
            payload={
                "document_id": str(document_id),
                "knowledge_base_id": str(scope.knowledge_base_id),
                "user_id": str(scope.user_id),
            },
        )
    )
    return True


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
            JobType.BUILD_GRAPH,
            JobType.GENERATE_EMBEDDINGS,
            JobType.COMPACT_MEMORY,
            JobType.OCR_PAGE,
            # Claimed so it can be completed. A job type nothing claims is not idle,
            # it is a queue that grows for ever.
            JobType.SYNC_GRAPH_PROJECTION,
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
