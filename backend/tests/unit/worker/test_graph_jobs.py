"""Tests for the graph job types the worker dispatches.

Three things are covered, and the first is the one that mattered: graph extraction was
built, tested and left with nothing to run it. `BuildGraphUseCase` existed, the answer
path read the graph on every turn, and no job ever queued a build, so the graph was
always empty and the retrieval path that read it always found nothing.

  - BUILD_GRAPH is enqueued when a document finishes ingesting, but only for a
    Knowledge Base that asked for a graph.
  - BUILD_GRAPH dispatches to the build use case rather than falling through to the
    ingestion handler, which is what `_run_job` does with a type it does not know.
  - SYNC_GRAPH_PROJECTION completes without doing anything. It is a documented no-op,
    but a job type nothing claims is a queue that grows for ever.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.documents.entities import Document, DocumentPage, ParsedPage
from app.domain.enums import DocumentStatus, JobPriority, JobStatus, JobType, PageKind
from app.domain.jobs.entities import ProcessingJob
from app.domain.knowledge_base.entities import KnowledgeBase
from app.worker.__main__ import _run_job

_NOW = datetime(2025, 1, 15, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _job(job_type: JobType) -> ProcessingJob:
    return ProcessingJob(
        id=uuid.uuid4(),
        job_type=job_type,
        priority=JobPriority.BACKGROUND,
        status=JobStatus.RUNNING,
        attempt_count=1,
        max_attempts=3,
        created_at=_NOW,
        updated_at=_NOW,
        lease_expires_at=_NOW + timedelta(seconds=300),
        payload={
            "document_id": str(_DOC_ID),
            "knowledge_base_id": str(_KB_ID),
            "user_id": str(_USER_ID),
        },
    )


def _doc(status: DocumentStatus = DocumentStatus.PENDING) -> Document:
    return Document(
        id=_DOC_ID,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        filename="lecture.pdf",
        content_type="application/pdf",
        byte_size=1024,
        storage_key=f"{_USER_ID}/{_KB_ID}/{_DOC_ID}/original.pdf",
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        page_count=5,
    )


def _kb(*, graph_enabled: bool) -> KnowledgeBase:
    return KnowledgeBase(
        id=_KB_ID,
        user_id=_USER_ID,
        name="Knowledge base",
        graph_enabled=graph_enabled,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _settings() -> MagicMock:
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
    return s


def _container() -> MagicMock:
    session = AsyncMock()
    session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    container = MagicMock()
    container.session_factory = MagicMock(return_value=ctx)
    return container


def _empty_page_parser() -> AsyncMock:
    """A parser returning one page with nothing on it — enough to complete ingestion."""
    parser = AsyncMock()
    parser.parse = AsyncMock(
        return_value=[
            ParsedPage(
                page=DocumentPage(
                    id=uuid.uuid4(),
                    user_id=_USER_ID,
                    knowledge_base_id=_KB_ID,
                    document_id=_DOC_ID,
                    page_number=1,
                    kind=PageKind.SCANNED,
                    width=612.0,
                    height=792.0,
                ),
                elements=[],
            )
        ]
    )
    return parser


def _ingestion_container() -> MagicMock:
    container = _container()
    storage = AsyncMock()
    storage.get = AsyncMock(return_value=b"%PDF fake")
    embedder = AsyncMock()
    embedder.embed_documents = AsyncMock(return_value=[])
    embedder.dimension = 384
    container.storage = storage
    container.embedder = embedder
    container.pdf_parser = _empty_page_parser()
    return container


async def _run_ingestion_with(*, graph_enabled: bool) -> list[ProcessingJob]:
    """Run one ingestion to completion and return every job that was saved."""
    saved_jobs: list[ProcessingJob] = []

    doc_repo = AsyncMock()
    doc_repo.get = AsyncMock(return_value=_doc())
    doc_repo.save = AsyncMock()

    job_repo = AsyncMock()
    job_repo.save = AsyncMock(side_effect=saved_jobs.append)

    chunk_repo = AsyncMock()
    chunk_repo.save_batch = AsyncMock()
    chunk_repo.set_embeddings = AsyncMock()

    kb_repo = AsyncMock()
    kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=graph_enabled))

    with (
        patch("app.worker.__main__.SqlDocumentRepository", return_value=doc_repo),
        patch("app.worker.__main__.SqlChunkRepository", return_value=chunk_repo),
        patch("app.worker.__main__.SqlJobRepository", return_value=job_repo),
        patch("app.worker.__main__.SqlKnowledgeBaseRepository", return_value=kb_repo),
    ):
        await _run_job(_ingestion_container(), _settings(), _job(JobType.DOCUMENT_INGESTION))

    return saved_jobs


# ---------------------------------------------------------------------------
# BUILD_GRAPH is queued when ingestion finishes
# ---------------------------------------------------------------------------


class TestGraphBuildEnqueued:
    async def test_graph_enabled_kb_gets_a_build_job(self) -> None:
        saved = await _run_ingestion_with(graph_enabled=True)
        assert any(j.job_type is JobType.BUILD_GRAPH for j in saved)

    async def test_build_job_names_the_document_just_ingested(self) -> None:
        saved = await _run_ingestion_with(graph_enabled=True)
        build = next(j for j in saved if j.job_type is JobType.BUILD_GRAPH)
        assert build.payload["document_id"] == str(_DOC_ID)
        assert build.payload["knowledge_base_id"] == str(_KB_ID)
        assert build.payload["user_id"] == str(_USER_ID)

    async def test_build_job_runs_behind_interactive_work(self) -> None:
        """Nothing waits on the graph, and a missing one degrades rather than breaks."""
        saved = await _run_ingestion_with(graph_enabled=True)
        build = next(j for j in saved if j.job_type is JobType.BUILD_GRAPH)
        assert build.priority is JobPriority.BACKGROUND
        assert build.status is JobStatus.PENDING

    async def test_graph_disabled_kb_gets_no_build_job(self) -> None:
        """Extraction costs a model call per section, so it stays opt-in."""
        saved = await _run_ingestion_with(graph_enabled=False)
        assert not any(j.job_type is JobType.BUILD_GRAPH for j in saved)

    async def test_ingestion_still_completes_either_way(self) -> None:
        for enabled in (True, False):
            saved = await _run_ingestion_with(graph_enabled=enabled)
            assert any(j.status is JobStatus.COMPLETED for j in saved)


# ---------------------------------------------------------------------------
# BUILD_GRAPH dispatches to the build use case
# ---------------------------------------------------------------------------


class TestGraphBuildDispatch:
    async def test_build_graph_job_reaches_the_use_case(self) -> None:
        """An unrecognised type falls through to ingestion, so this must be explicit."""
        with (
            patch("app.worker.__main__.BuildGraphUseCase") as MockBuild,
            patch("app.worker.__main__.SqlKnowledgeBaseRepository"),
            patch("app.worker.__main__.SqlDocumentRepository"),
            patch("app.worker.__main__.SqlChunkRepository"),
            patch("app.worker.__main__.SqlGraphRepository"),
            patch("app.worker.__main__.SqlJobRepository", return_value=AsyncMock()),
            patch("app.worker.__main__.LlmGraphExtractor"),
        ):
            MockBuild.return_value.execute = AsyncMock()
            await _run_job(_container(), _settings(), _job(JobType.BUILD_GRAPH))

            command = MockBuild.return_value.execute.call_args[0][0]

        assert command.document_id == _DOC_ID
        assert command.scope.knowledge_base_id == _KB_ID
        assert command.scope.user_id == _USER_ID

    async def test_build_graph_job_is_completed_afterwards(self) -> None:
        saved_jobs: list[ProcessingJob] = []
        job_repo = AsyncMock()
        job_repo.save = AsyncMock(side_effect=saved_jobs.append)

        with (
            patch("app.worker.__main__.BuildGraphUseCase") as MockBuild,
            patch("app.worker.__main__.SqlKnowledgeBaseRepository"),
            patch("app.worker.__main__.SqlDocumentRepository"),
            patch("app.worker.__main__.SqlChunkRepository"),
            patch("app.worker.__main__.SqlGraphRepository"),
            patch("app.worker.__main__.SqlJobRepository", return_value=job_repo),
            patch("app.worker.__main__.LlmGraphExtractor"),
        ):
            MockBuild.return_value.execute = AsyncMock()
            await _run_job(_container(), _settings(), _job(JobType.BUILD_GRAPH))

        assert any(j.status is JobStatus.COMPLETED for j in saved_jobs)

    async def test_extractor_is_built_on_the_model_gateway(self) -> None:
        """The one collaborator that is not a repository, and the reason none was needed."""
        container = _container()

        with (
            patch("app.worker.__main__.BuildGraphUseCase") as MockBuild,
            patch("app.worker.__main__.SqlKnowledgeBaseRepository"),
            patch("app.worker.__main__.SqlDocumentRepository"),
            patch("app.worker.__main__.SqlChunkRepository"),
            patch("app.worker.__main__.SqlGraphRepository"),
            patch("app.worker.__main__.SqlJobRepository", return_value=AsyncMock()),
            patch("app.worker.__main__.LlmGraphExtractor") as MockExtractor,
        ):
            MockBuild.return_value.execute = AsyncMock()
            await _run_job(container, _settings(), _job(JobType.BUILD_GRAPH))

        MockExtractor.assert_called_once_with(container.model_gateway)


# ---------------------------------------------------------------------------
# SYNC_GRAPH_PROJECTION is claimed and completed without work
# ---------------------------------------------------------------------------


class TestGraphProjectionNoop:
    async def test_projection_job_is_completed(self) -> None:
        """Unclaimed, it would accumulate as PENDING rows that look like a backlog."""
        saved_jobs: list[ProcessingJob] = []
        job_repo = AsyncMock()
        job_repo.save = AsyncMock(side_effect=saved_jobs.append)

        with patch("app.worker.__main__.SqlJobRepository", return_value=job_repo):
            await _run_job(
                _container(), _settings(), _job(JobType.SYNC_GRAPH_PROJECTION)
            )

        assert len(saved_jobs) == 1
        assert saved_jobs[0].status is JobStatus.COMPLETED

    async def test_projection_job_does_not_reach_the_build_use_case(self) -> None:
        """There is no second store to synchronise; the type is kept for the schema."""
        job_repo = AsyncMock()

        with (
            patch("app.worker.__main__.SqlJobRepository", return_value=job_repo),
            patch("app.worker.__main__.BuildGraphUseCase") as MockBuild,
        ):
            await _run_job(
                _container(), _settings(), _job(JobType.SYNC_GRAPH_PROJECTION)
            )

        MockBuild.assert_not_called()
