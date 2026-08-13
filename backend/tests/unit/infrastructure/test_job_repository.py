"""Tests for SqlJobRepository using mock AsyncSession.

ProcessingJobModel uses JSONB for the payload column, which SQLite does not
support. All tests use AsyncMock sessions. claim_next uses SELECT ... FOR UPDATE
SKIP LOCKED, which is PostgreSQL-specific; the tests verify the SELECT is issued
and that the claim lifecycle runs correctly through the domain entity.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.job import ProcessingJobModel
from app.infrastructure.database.repositories.job import SqlJobRepository


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_job_model(
    status: JobStatus = JobStatus.PENDING,
    job_type: JobType = JobType.DOCUMENT_INGESTION,
) -> ProcessingJobModel:
    ts = datetime.now(UTC)
    kb_id = str(uuid.uuid4())
    return ProcessingJobModel(
        id=uuid.uuid4(),
        job_type=job_type.value,
        priority=int(JobPriority.NORMAL),
        status=status.value,
        attempt_count=0,
        max_attempts=3,
        payload={"knowledge_base_id": kb_id, "document_id": str(uuid.uuid4())},
        created_at=ts,
        updated_at=ts,
    )


def _make_job(
    status: JobStatus = JobStatus.PENDING,
    job_type: JobType = JobType.DOCUMENT_INGESTION,
) -> ProcessingJob:
    ts = datetime.now(UTC)
    return ProcessingJob(
        id=uuid.uuid4(),
        job_type=job_type,
        priority=JobPriority.NORMAL,
        status=status,
        attempt_count=0,
        max_attempts=3,
        payload={"knowledge_base_id": str(uuid.uuid4())},
        created_at=ts,
        updated_at=ts,
    )


def _mock_result_scalar_none() -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


def _mock_result_scalar(row: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    return result


def _mock_result_scalars(rows: list[object]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _repo(session: AsyncMock) -> SqlJobRepository:
    return SqlJobRepository(session=session)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_none_when_not_found(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        result = await _repo(session).get(uuid.uuid4())
        assert result is None
        session.execute.assert_called_once()

    async def test_maps_row_to_entity(self) -> None:
        session = AsyncMock()
        model = _make_job_model()
        session.execute = AsyncMock(return_value=_mock_result_scalar(model))
        result = await _repo(session).get(model.id)
        assert result is not None
        assert result.id == model.id
        assert result.status == JobStatus.PENDING
        assert result.priority == JobPriority.NORMAL


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    async def test_calls_merge(self) -> None:
        session = AsyncMock()
        session.merge = AsyncMock(return_value=MagicMock())
        job = _make_job()
        await _repo(session).save(job)
        session.merge.assert_called_once()


# ---------------------------------------------------------------------------
# claim_next
# ---------------------------------------------------------------------------


class TestClaimNext:
    async def test_returns_none_when_no_pending_job(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        repo = _repo(session)

        result = await repo.claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )

        assert result is None
        session.execute.assert_called_once()
        session.merge.assert_not_called()

    async def test_claims_pending_job_and_returns_running(self) -> None:
        session = AsyncMock()
        pending_model = _make_job_model(status=JobStatus.PENDING)
        session.execute = AsyncMock(return_value=_mock_result_scalar(pending_model))
        session.merge = AsyncMock(return_value=MagicMock())
        repo = _repo(session)

        lease = datetime.now(UTC) + timedelta(minutes=5)
        result = await repo.claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=lease,
        )

        assert result is not None
        assert result.status == JobStatus.RUNNING
        assert result.attempt_count == 1
        assert result.lease_expires_at == lease
        session.merge.assert_called_once()

    async def test_applies_job_type_filter(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        repo = _repo(session)

        await repo.claim_next(
            job_types=frozenset({JobType.GENERATE_EMBEDDINGS, JobType.BUILD_GRAPH}),
            worker_id="w-2",
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "GENERATE_EMBEDDINGS" in compiled
        assert "BUILD_GRAPH" in compiled


# ---------------------------------------------------------------------------
# list_for_scope
# ---------------------------------------------------------------------------


class TestListForScope:
    async def test_calls_execute_once(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        scope = _make_scope()
        await _repo(session).list_for_scope(scope)
        session.execute.assert_called_once()

    async def test_applies_knowledge_base_filter(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        scope = _make_scope()
        await _repo(session).list_for_scope(scope)

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert str(scope.knowledge_base_id) in compiled
