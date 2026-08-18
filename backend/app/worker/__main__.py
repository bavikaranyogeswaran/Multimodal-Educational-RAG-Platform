"""Ingestion worker — run with: python -m app.worker

One worker process claims document-ingestion jobs one at a time, runs the full pipeline
(download → parse → persist pages and elements → chunk → embed), and extends the job's
lease while work is in progress. On SIGTERM or SIGINT the worker finishes the current
job, then exits cleanly.

The heartbeat that holds the lease runs as a task on this same event loop, which is why
the parser hands its work to a thread rather than doing it here.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.commands.ingest_document import IngestDocumentCommand, IngestDocumentUseCase
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.configuration.wire import build_container
from app.domain.enums import DocumentStatus, JobStatus, JobType
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.job import SqlJobRepository

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

    # Phase 2: run the pipeline with a parallel heartbeat task
    heartbeat_stop = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_loop(
            container.session_factory,
            job,
            interval_seconds=settings.job.heartbeat_interval_seconds,
            lease_seconds=settings.job.lease_seconds,
            stop=heartbeat_stop,
        )
    )
    try:
        async with container.session_factory() as session:
            use_case = IngestDocumentUseCase(
                chunk_repo=SqlChunkRepository(scope, session),
                document_repo=SqlDocumentRepository(scope, session),
                storage=container.storage,
                embedder=container.embedder,
                parser=container.pdf_parser,
                embedding_model_id=settings.embedding.model_id,
                index_version=settings.embedding.index_version,
                chunk_chars=settings.chunking.child_target_tokens * 4,
                chunk_overlap_chars=settings.chunking.child_overlap_tokens * 4,
            )
            completed_doc = await use_case.execute(
                IngestDocumentCommand(scope=scope, document=processing_doc)
            )
            await SqlDocumentRepository(scope, session).save(scope, completed_doc)
            await SqlJobRepository(session).save(job.complete(now=datetime.now(UTC)))
            await session.commit()
    finally:
        heartbeat_stop.set()
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

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
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    _log.info("worker_started", worker_id=worker_id)

    while not shutdown.is_set():
        # Claim the highest-priority pending ingestion job
        async with container.session_factory() as session:
            job = await SqlJobRepository(session).claim_next(
                job_types=frozenset({JobType.DOCUMENT_INGESTION}),
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
                    if failed.status is JobStatus.DEAD_LETTER:
                        doc_repo = SqlDocumentRepository(scope, session)
                        doc = await doc_repo.get(scope, doc_id)
                        if doc is not None and not doc.status.is_terminal:
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
    asyncio.run(_main())
