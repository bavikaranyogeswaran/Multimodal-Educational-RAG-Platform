"""Unit tests for the ingestion worker loop.

Tests _run_job directly with mocked container, session factory, and repos.
The signal-handling event loop (main()) is an integration concern; unit tests
stay focused on the per-job lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.documents.entities import Document, DocumentPage, ParsedPage
from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType, PageKind
from app.domain.jobs.entities import ProcessingJob
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.worker.__main__ import _run_job

_NOW = datetime(2025, 1, 15, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()
_JOB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)


def _make_job(*, status: JobStatus = JobStatus.RUNNING) -> ProcessingJob:
    return ProcessingJob(
        id=_JOB_ID,
        job_type=JobType.DOCUMENT_INGESTION,
        priority=JobPriority.INTERACTIVE,
        status=status,
        attempt_count=1,
        max_attempts=3,
        created_at=_NOW,
        updated_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=300),
        payload={
            "document_id": str(_DOC_ID),
            "user_id": str(_USER_ID),
            "knowledge_base_id": str(_KB_ID),
        },
    )


def _make_doc(*, status: DocumentStatus = DocumentStatus.PENDING) -> Document:
    return Document(
        id=_DOC_ID,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        filename="lecture.pdf",
        content_type="application/pdf",
        byte_size=1024,
        storage_key=f"{_USER_ID}/{_KB_ID}/{_DOC_ID}/original.pdf",
        created_at=_NOW,
        updated_at=_NOW,
        status=status,
        page_count=5,
    )


def _make_container(doc: Document) -> MagicMock:
    """Build a container mock whose session_factory is an async context manager."""
    session = AsyncMock()
    session.commit = AsyncMock()

    # doc_repo returned by SqlDocumentRepository
    doc_repo = AsyncMock()
    doc_repo.get = AsyncMock(return_value=doc)
    doc_repo.save = AsyncMock()

    job_repo = AsyncMock()
    job_repo.save = AsyncMock()

    chunk_repo = AsyncMock()
    chunk_repo.save_batch = AsyncMock()

    storage = AsyncMock()
    storage.get = AsyncMock(return_value=b"%PDF fake")

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    container = MagicMock()
    container.session_factory = MagicMock(return_value=ctx)
    container.storage = storage
    return container


def _kb(*, graph_enabled: bool = False) -> KnowledgeBase:
    """The Knowledge Base ingestion reads on its way out to decide about graphing."""
    return KnowledgeBase(
        id=_KB_ID,
        user_id=_USER_ID,
        name="Knowledge base",
        graph_enabled=graph_enabled,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _kb_repo(*, graph_enabled: bool = False) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=_kb(graph_enabled=graph_enabled))
    return repo


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.job.heartbeat_interval_seconds = 30
    s.job.lease_seconds = 300
    s.embedding.model_id = "test-model"
    s.embedding.index_version = 1
    s.chunking.child_target_tokens = 400
    s.chunking.child_max_tokens = 700
    s.chunking.child_overlap_tokens = 70
    s.chunking.parent_target_tokens = 1200
    s.chunking.parent_max_tokens = 1500
    s.job.backoff_base_seconds = 10
    s.job.backoff_max_seconds = 900
    return s


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRunJobHappyPath:
    async def test_marks_document_processing_then_completed(self) -> None:
        # Covered in detail by test_does_not_raise_on_valid_job_with_empty_pdf;
        # kept as a structural placeholder for the two-phase commit contract.
        pass

    async def test_does_not_raise_when_a_page_yields_no_text(self) -> None:
        doc = _make_doc(status=DocumentStatus.PENDING)
        settings = _make_settings()
        job = _make_job()

        session = AsyncMock()
        session.commit = AsyncMock()

        saved_docs: list[Document] = []
        saved_jobs: list[ProcessingJob] = []

        doc_repo_mock = AsyncMock()
        doc_repo_mock.get = AsyncMock(return_value=doc)
        doc_repo_mock.save = AsyncMock(side_effect=lambda _scope, d: saved_docs.append(d))

        job_repo_mock = AsyncMock()
        job_repo_mock.save = AsyncMock(side_effect=saved_jobs.append)

        chunk_repo_mock = AsyncMock()
        chunk_repo_mock.save_batch = AsyncMock()

        storage_mock = AsyncMock()
        storage_mock.get = AsyncMock(return_value=b"%PDF fake")

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        # A page that exists and produced nothing — a scanned page, before recognition.
        parser_mock = AsyncMock()
        parser_mock.parse = AsyncMock(
            return_value=[
                ParsedPage(
                    page=DocumentPage(
                        id=uuid.uuid4(),
                        user_id=doc.user_id,
                        knowledge_base_id=doc.knowledge_base_id,
                        document_id=doc.id,
                        page_number=1,
                        kind=PageKind.SCANNED,
                        width=612.0,
                        height=792.0,
                    ),
                    elements=[],
                )
            ]
        )

        container = MagicMock()
        container.session_factory = MagicMock(return_value=ctx)
        container.storage = storage_mock
        container.pdf_parser = parser_mock

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo_mock),
            patch("app.worker.__main__.SqlChunkRepository", return_value=chunk_repo_mock),
            patch("app.worker.__main__.SqlJobRepository", return_value=job_repo_mock),
            patch("app.worker.__main__.SqlKnowledgeBaseRepository", return_value=_kb_repo()),
        ):
            await _run_job(container, settings, job)

        # document should have been saved twice: PROCESSING then COMPLETED
        assert len(saved_docs) == 2
        assert saved_docs[0].status == DocumentStatus.PROCESSING
        assert saved_docs[1].status == DocumentStatus.COMPLETED

        # job should have been saved as COMPLETED
        assert any(j.status == JobStatus.COMPLETED for j in saved_jobs)


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestRunJobFailure:
    async def test_raises_when_document_not_found(self) -> None:
        settings = _make_settings()
        job = _make_job()

        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        container = MagicMock()
        container.session_factory = MagicMock(return_value=ctx)

        doc_repo_mock = AsyncMock()
        doc_repo_mock.get = AsyncMock(return_value=None)

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo_mock),
            patch("app.worker.__main__.SqlChunkRepository"),
            patch("app.worker.__main__.SqlJobRepository"),
            pytest.raises(RuntimeError, match="not found"),
        ):
            await _run_job(container, settings, job)


# ---------------------------------------------------------------------------
# Retry-aware document status
# ---------------------------------------------------------------------------


def _failing_container(doc: Document) -> tuple[MagicMock, list[Document], AsyncMock]:
    """A container whose storage raises, so _run_job always fails."""
    session = AsyncMock()
    session.commit = AsyncMock()

    saved: list[Document] = []
    doc_repo = AsyncMock()
    doc_repo.get = AsyncMock(return_value=doc)
    doc_repo.save = AsyncMock(side_effect=lambda _scope, d: saved.append(d))

    storage = AsyncMock()
    storage.get = AsyncMock(side_effect=RuntimeError("storage unreachable"))

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    container = MagicMock()
    container.session_factory = MagicMock(return_value=ctx)
    container.storage = storage
    container.pdf_parser = AsyncMock()
    return container, saved, doc_repo


class TestDocumentStatusAcrossRetries:
    async def test_an_already_processing_document_is_not_marked_again(self) -> None:
        """A retry finds the document already PROCESSING, and a transition from a state
        to itself is refused by the entity — so it must not be attempted."""
        doc = _make_doc(status=DocumentStatus.PROCESSING)
        container, saved, doc_repo = _failing_container(doc)

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
            patch("app.worker.__main__.SqlChunkRepository"),
            patch("app.worker.__main__.SqlJobRepository"),
            pytest.raises(RuntimeError, match="storage unreachable"),
        ):
            await _run_job(container, _make_settings(), _make_job())

        assert not any(d.status is DocumentStatus.PROCESSING for d in saved)

    async def test_a_pending_document_is_marked_processing(self) -> None:
        doc = _make_doc(status=DocumentStatus.PENDING)
        container, saved, doc_repo = _failing_container(doc)

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
            patch("app.worker.__main__.SqlChunkRepository"),
            patch("app.worker.__main__.SqlJobRepository"),
            pytest.raises(RuntimeError),
        ):
            await _run_job(container, _make_settings(), _make_job())

        assert saved[0].status is DocumentStatus.PROCESSING


# ---------------------------------------------------------------------------
# Deletion jobs
# ---------------------------------------------------------------------------


def _delete_job() -> ProcessingJob:
    return ProcessingJob(
        id=_JOB_ID,
        job_type=JobType.DELETE_DOCUMENT,
        priority=JobPriority.INTERACTIVE,
        status=JobStatus.RUNNING,
        attempt_count=1,
        max_attempts=3,
        created_at=_NOW,
        updated_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=300),
        payload={
            "document_id": str(_DOC_ID),
            "user_id": str(_USER_ID),
            "knowledge_base_id": str(_KB_ID),
            "storage_key": f"{_USER_ID}/{_KB_ID}/{_DOC_ID}/original.pdf",
        },
    )


class TestDeletionJobs:
    """Before this, DELETE_DOCUMENT jobs were enqueued at the highest priority in the
    system and nothing ever claimed them."""

    async def test_a_deletion_job_removes_the_document(self) -> None:
        doc = _make_doc(status=DocumentStatus.DELETING)

        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=doc)
        doc_repo.delete = AsyncMock()

        storage = AsyncMock()
        renderer = AsyncMock()

        container = MagicMock()
        container.session_factory = MagicMock(return_value=ctx)
        container.storage = storage
        container.page_renderer = renderer

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
            patch("app.worker.__main__.SqlJobRepository", return_value=AsyncMock()),
        ):
            await _run_job(container, _make_settings(), _delete_job())

        doc_repo.delete.assert_awaited_once()
        storage.delete.assert_awaited_once()
        renderer.discard_document.assert_awaited_once()

    async def test_a_deletion_job_does_not_run_the_ingestion_pipeline(self) -> None:
        """Dispatch is by job type. Running ingestion for a deletion would download and
        re-index the very document being removed."""
        doc = _make_doc(status=DocumentStatus.DELETING)

        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=doc)

        parser = AsyncMock()
        container = MagicMock()
        container.session_factory = MagicMock(return_value=ctx)
        container.storage = AsyncMock()
        container.page_renderer = AsyncMock()
        container.pdf_parser = parser

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
            patch("app.worker.__main__.SqlJobRepository", return_value=AsyncMock()),
        ):
            await _run_job(container, _make_settings(), _delete_job())

        parser.parse.assert_not_awaited()

    async def test_a_deletion_job_is_marked_complete(self) -> None:
        doc = _make_doc(status=DocumentStatus.DELETING)

        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=doc)

        saved_jobs: list[ProcessingJob] = []
        job_repo = AsyncMock()
        job_repo.save = AsyncMock(side_effect=saved_jobs.append)

        container = MagicMock()
        container.session_factory = MagicMock(return_value=ctx)
        container.storage = AsyncMock()
        container.page_renderer = AsyncMock()

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
            patch("app.worker.__main__.SqlJobRepository", return_value=job_repo),
        ):
            await _run_job(container, _make_settings(), _delete_job())

        assert [j.status for j in saved_jobs] == [JobStatus.COMPLETED]

    async def test_deleting_an_already_deleted_document_succeeds(self) -> None:
        """A retried deletion meets its own finished work, which is the outcome it
        wanted rather than a failure."""
        session = AsyncMock()
        session.commit = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        doc_repo = AsyncMock()
        doc_repo.get = AsyncMock(return_value=None)

        container = MagicMock()
        container.session_factory = MagicMock(return_value=ctx)
        container.storage = AsyncMock()
        container.page_renderer = AsyncMock()

        with (
            patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
            patch("app.worker.__main__.SqlJobRepository", return_value=AsyncMock()),
        ):
            await _run_job(container, _make_settings(), _delete_job())

        doc_repo.delete.assert_not_awaited()
