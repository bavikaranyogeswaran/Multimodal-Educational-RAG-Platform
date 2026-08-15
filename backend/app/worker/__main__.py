"""Ingestion worker — run with: python -m app.worker

One worker process claims document-ingestion jobs one at a time, runs the full
pipeline (download → chunk → embed → persist), and extends the job's lease
while work is in progress. On SIGTERM or SIGINT the worker finishes the current
job, then exits cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import signal
import uuid
from datetime import UTC, datetime, timedelta

import pypdf
import structlog

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.commands.ingest_document import IngestDocumentCommand, IngestDocumentUseCase
from app.configuration.container import Container
from app.configuration.settings import Settings, get_settings
from app.configuration.wire import build_container
from app.domain.enums import JobType
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.database.repositories.document import SqlDocumentRepository
from app.infrastructure.database.repositories.job import SqlJobRepository

_log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# PDF text extractor (infrastructure concern, kept here so the app layer
# remains free of pypdf imports)
# ---------------------------------------------------------------------------


def _extract_pdf_pages(data: bytes) -> list[tuple[int, str]]:
    """Return (1-indexed page number, extracted text) for each page with text."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    result: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            result.append((i, text))
    return result


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
                storage=container.storage,
                embedder=container.embedder,
                pdf_page_extractor=_extract_pdf_pages,
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
            try:
                doc_id = uuid.UUID(job.payload["document_id"])
                user_id = uuid.UUID(job.payload["user_id"])
                kb_id = uuid.UUID(job.payload["knowledge_base_id"])
                scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
                async with container.session_factory() as session:
                    doc_repo = SqlDocumentRepository(scope, session)
                    doc = await doc_repo.get(scope, doc_id)
                    if doc is not None and not doc.status.is_terminal:
                        await doc_repo.save(scope, doc.mark_failed(reason, now=now))
                    await SqlJobRepository(session).save(job.fail(reason=reason, now=now))
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
