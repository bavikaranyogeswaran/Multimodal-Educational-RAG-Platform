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

from sqlalchemy.dialects import postgresql

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


def _make_failed_model(
    *,
    attempt_count: int = 1,
    max_attempts: int = 3,
    retry_at: datetime | None = None,
) -> ProcessingJobModel:
    """A job that has failed once and is waiting for its next attempt."""
    model = _make_job_model(status=JobStatus.FAILED)
    model.attempt_count = attempt_count
    model.max_attempts = max_attempts
    model.failure_reason = "connection timeout"
    model.scheduled_at = retry_at
    return model


def _make_running_model(
    *,
    attempt_count: int = 1,
    max_attempts: int = 3,
    lease_expires_at: datetime | None = None,
) -> ProcessingJobModel:
    """A job a worker is holding, with whatever lease the caller wants to test."""
    model = _make_job_model(status=JobStatus.RUNNING)
    model.attempt_count = attempt_count
    model.max_attempts = max_attempts
    model.lease_expires_at = lease_expires_at or (datetime.now(UTC) + timedelta(minutes=5))
    model.last_heartbeat_at = datetime.now(UTC)
    return model


def _mock_result_scalars(rows: list[object]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


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


# ---------------------------------------------------------------------------
# claim_next — retries
# ---------------------------------------------------------------------------


class TestClaimNextPicksUpRetries:
    """Failed jobs return to work through the same query that finds new work.

    Before this, nothing requeued them: `requeue` existed and no caller ever called it,
    so a job that failed once stayed failed and `max_attempts` meant nothing.
    """

    async def test_a_failed_job_is_claimed(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_mock_result_scalar(_make_failed_model())
        )

        claimed = await _repo(session).claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )

        assert claimed is not None
        assert claimed.status is JobStatus.RUNNING

    async def test_claiming_a_failed_job_counts_the_new_attempt(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_mock_result_scalar(_make_failed_model(attempt_count=1))
        )

        claimed = await _repo(session).claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )

        assert claimed is not None
        assert claimed.attempt_count == 2

    async def test_a_reclaimed_job_forgets_its_previous_failure(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_mock_result_scalar(_make_failed_model())
        )

        claimed = await _repo(session).claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )

        assert claimed is not None
        assert claimed.failure_reason is None

    async def test_a_claimed_retry_holds_a_lease(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=_mock_result_scalar(_make_failed_model())
        )
        lease_until = datetime.now(UTC) + timedelta(minutes=5)

        claimed = await _repo(session).claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=lease_until,
        )

        assert claimed is not None
        assert claimed.lease_expires_at == lease_until


class TestClaimNextQuery:
    """What the SELECT asks for, checked through its bound parameters.

    The query is PostgreSQL-specific and cannot run here, so these read the compiled
    parameters — the same approach the retrieval security tests use.
    """

    async def _claim(self, session: AsyncMock) -> None:
        await _repo(session).claim_next(
            job_types=frozenset({JobType.DOCUMENT_INGESTION}),
            worker_id="w-1",
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
        )

    async def test_both_pending_and_failed_are_sought(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        await self._claim(session)

        params = session.execute.call_args[0][0].compile().params
        assert JobStatus.PENDING.value in params.values()
        assert JobStatus.FAILED.value in params.values()

    async def test_a_scheduled_time_in_the_future_is_excluded(self) -> None:
        """The backoff is enforced in the query, so a job that is not yet due is never
        handed to a worker in the first place."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        await self._claim(session)

        sql = str(session.execute.call_args[0][0])
        assert "scheduled_at IS NULL" in sql
        assert "scheduled_at <=" in sql

    async def test_exhausted_attempts_are_excluded(self) -> None:
        """Guards the requeue, which refuses a job with no attempts left."""
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        await self._claim(session)

        sql = str(session.execute.call_args[0][0])
        assert "attempt_count < processing_jobs.max_attempts" in sql

    async def test_priority_still_orders_the_queue(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        await self._claim(session)

        sql = str(session.execute.call_args[0][0])
        assert "ORDER BY processing_jobs.priority DESC" in sql


# ---------------------------------------------------------------------------
# Lease-expiry reclaim
# ---------------------------------------------------------------------------


def _expired(**kwargs: object) -> ProcessingJobModel:
    kwargs.setdefault("lease_expires_at", datetime.now(UTC) - timedelta(minutes=1))
    return _make_running_model(**kwargs)  # type: ignore[arg-type]


async def _reclaim(session: AsyncMock, **overrides: object) -> list[ProcessingJob]:
    kwargs: dict[str, object] = {
        "job_types": frozenset({JobType.DOCUMENT_INGESTION}),
        "now": datetime.now(UTC),
        "backoff_base_seconds": 10,
        "backoff_max_seconds": 900,
    }
    kwargs.update(overrides)
    return list(await _repo(session).reclaim_expired(**kwargs))  # type: ignore[arg-type]


def _returning(rows: list[object]) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_result_scalars(rows))
    return session


class TestReclaimExpired:
    """A job whose worker died would otherwise sit as RUNNING for ever, because no
    worker claims a job that another one appears to be doing."""

    async def test_an_expired_job_is_reclaimed(self) -> None:
        reclaimed = await _reclaim(_returning([_expired()]))

        assert len(reclaimed) == 1
        assert reclaimed[0].status is JobStatus.FAILED

    async def test_the_lost_attempt_is_counted(self) -> None:
        """It was an attempt and it consumed one. A job that reliably kills whatever
        picks it up would otherwise retry for ever, always looking untried."""
        reclaimed = await _reclaim(_returning([_expired(attempt_count=2)]))

        assert reclaimed[0].attempt_count == 2

    async def test_a_reclaimed_job_waits_out_a_backoff(self) -> None:
        """The job may be what killed the worker, so retrying it instantly would
        reproduce the crash as fast as the machine allows."""
        now = datetime.now(UTC)
        reclaimed = await _reclaim(_returning([_expired()]), now=now)

        assert reclaimed[0].scheduled_at is not None
        assert reclaimed[0].scheduled_at > now

    async def test_the_reason_says_what_happened(self) -> None:
        reclaimed = await _reclaim(_returning([_expired()]))

        assert reclaimed[0].failure_reason is not None
        assert "lease expired" in reclaimed[0].failure_reason

    async def test_the_lease_is_released(self) -> None:
        reclaimed = await _reclaim(_returning([_expired()]))

        assert reclaimed[0].lease_expires_at is None

    async def test_a_last_attempt_dead_letters_rather_than_looping(self) -> None:
        """Repeated crashes have to stop somewhere, and stopping loudly beats retrying
        quietly for ever."""
        reclaimed = await _reclaim(
            _returning([_expired(attempt_count=3, max_attempts=3)])
        )

        assert reclaimed[0].status is JobStatus.DEAD_LETTER
        assert reclaimed[0].scheduled_at is None

    async def test_nothing_expired_reclaims_nothing(self) -> None:
        session = _returning([])

        assert await _reclaim(session) == []
        session.merge.assert_not_called()

    async def test_every_expired_job_is_reclaimed(self) -> None:
        reclaimed = await _reclaim(_returning([_expired() for _ in range(3)]))

        assert len(reclaimed) == 3


class TestReclaimQuery:
    """What the sweep asks for, read from the compiled statement."""

    async def test_only_running_jobs_are_swept(self) -> None:
        session = _returning([])
        await _reclaim(session)

        params = session.execute.call_args[0][0].compile().params
        assert JobStatus.RUNNING.value in params.values()

    async def test_a_valid_lease_is_not_swept(self) -> None:
        """A worker that is quiet but within its lease is still working. Sweeping it
        would take the job away from a process that is about to finish it."""
        session = _returning([])
        await _reclaim(session)

        sql = str(session.execute.call_args[0][0])
        assert "lease_expires_at <" in sql
        assert "lease_expires_at IS NOT NULL" in sql

    async def test_the_sweep_skips_rows_another_worker_holds(self) -> None:
        """Compiled against PostgreSQL: SKIP LOCKED is dialect-specific, and the default
        dialect silently drops it, which would make this assertion pass on a query that
        never had it."""
        session = _returning([])
        await _reclaim(session)

        sql = str(
            session.execute.call_args[0][0].compile(dialect=postgresql.dialect())
        )
        assert "FOR UPDATE SKIP LOCKED" in sql

    async def test_only_eligible_job_types_are_swept(self) -> None:
        session = _returning([])
        await _reclaim(session, job_types=frozenset({JobType.DELETE_DOCUMENT}))

        params = session.execute.call_args[0][0].compile().params
        assert [JobType.DELETE_DOCUMENT.value] in params.values()
