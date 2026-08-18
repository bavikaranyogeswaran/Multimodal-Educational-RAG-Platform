"""SQLAlchemy implementation of JobRepository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.jobs.entities import ProcessingJob
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.job import ProcessingJobModel

_log = structlog.get_logger(__name__)


class SqlJobRepository:
    """Reads and writes ProcessingJob aggregates via SQLAlchemy.

    Worker operations (get, save, claim_next) do not take ScopeContext because a
    worker processes jobs across all users. This class therefore does not inherit
    from ScopedRepository, which requires a scope at construction time.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job_id: UUID) -> ProcessingJob | None:
        stmt = select(ProcessingJobModel).where(ProcessingJobModel.id == job_id)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def save(self, job: ProcessingJob) -> None:
        await self._session.merge(_to_model(job))

    async def claim_next(
        self,
        *,
        job_types: frozenset[JobType],
        worker_id: str,
        lease_until: datetime,
    ) -> ProcessingJob | None:
        """Atomically claim the highest-priority claimable job of an eligible type.

        Claimable means either never yet attempted, or failed with attempts remaining and
        its backoff elapsed. Retries are found by the same query that finds new work
        rather than by a separate scheduler — one query, one transaction, and no window
        in which a job is due but nothing has noticed.

        Uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent workers each claim a
        distinct row without blocking each other. PostgreSQL-specific.
        """
        now = datetime.now(UTC)
        stmt = (
            select(ProcessingJobModel)
            .where(
                ProcessingJobModel.job_type.in_([jt.value for jt in job_types]),
                sa.or_(
                    ProcessingJobModel.status == JobStatus.PENDING.value,
                    sa.and_(
                        ProcessingJobModel.status == JobStatus.FAILED.value,
                        # Guards the requeue below, which refuses a job with no attempts
                        # left. A dead-lettered job is already excluded by its status;
                        # this also excludes one that reached the limit some other way.
                        ProcessingJobModel.attempt_count < ProcessingJobModel.max_attempts,
                    ),
                ),
                sa.or_(
                    ProcessingJobModel.scheduled_at.is_(None),
                    ProcessingJobModel.scheduled_at <= now,
                ),
            )
            .order_by(ProcessingJobModel.priority.desc(), ProcessingJobModel.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None

        job = _to_entity(row)
        # A failed job returns to the queue before it can be claimed, because claiming is
        # a transition out of PENDING. Both moves land in the same transaction, so no
        # observer sees the job sitting requeued but unclaimed.
        if job.status is JobStatus.FAILED:
            job = job.requeue(now=now)
        claimed = job.claim(lease_until=lease_until, now=now)
        await self._session.merge(_to_model(claimed))
        return claimed

    async def reclaim_expired(
        self,
        *,
        job_types: frozenset[JobType],
        now: datetime,
        backoff_base_seconds: int,
        backoff_max_seconds: int,
    ) -> Sequence[ProcessingJob]:
        """Fail every job whose lease has lapsed, so the retry path can pick it up.

        Kept separate from claiming rather than folded into it. A reclaimed job is not
        immediately claimable — it has just failed, so it waits out a backoff like any
        other failure — and a method called `claim_next` that wrote to the database and
        then returned nothing would be a surprising thing to read. Backoff matters here
        precisely because the job may be what killed the worker: retrying it instantly
        would reproduce the crash as fast as the machine allows.

        Uses SELECT ... FOR UPDATE SKIP LOCKED so two workers sweeping at once do not
        both reclaim the same job. PostgreSQL-specific.
        """
        stmt = (
            select(ProcessingJobModel)
            .where(
                ProcessingJobModel.status == JobStatus.RUNNING.value,
                ProcessingJobModel.job_type.in_([jt.value for jt in job_types]),
                ProcessingJobModel.lease_expires_at.is_not(None),
                ProcessingJobModel.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.execute(stmt)).scalars().all()

        reclaimed: list[ProcessingJob] = []
        for row in rows:
            job = _to_entity(row).fail(
                reason="lease expired — the worker holding this job stopped responding",
                now=now,
                backoff_base_seconds=backoff_base_seconds,
                backoff_max_seconds=backoff_max_seconds,
            )
            await self._session.merge(_to_model(job))
            reclaimed.append(job)

        if reclaimed:
            _log.warning(
                "jobs_reclaimed",
                count=len(reclaimed),
                dead_lettered=sum(
                    1 for job in reclaimed if job.status is JobStatus.DEAD_LETTER
                ),
            )
        return reclaimed

    async def list_for_scope(self, scope: ScopeContext) -> Sequence[ProcessingJob]:
        """Jobs whose payload carries this knowledge base id. PostgreSQL-specific."""
        stmt = (
            select(ProcessingJobModel)
            .where(
                ProcessingJobModel.payload["knowledge_base_id"].as_string()
                == str(scope.knowledge_base_id),
            )
            .order_by(ProcessingJobModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _utc_opt(dt: datetime | None) -> datetime | None:
    return None if dt is None else _utc(dt)


def _to_entity(row: ProcessingJobModel) -> ProcessingJob:
    return ProcessingJob(
        id=row.id,
        job_type=JobType(row.job_type),
        priority=JobPriority(row.priority),
        status=JobStatus(row.status),
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        payload=row.payload,
        scheduled_at=_utc_opt(row.scheduled_at),
        lease_expires_at=_utc_opt(row.lease_expires_at),
        last_heartbeat_at=_utc_opt(row.last_heartbeat_at),
        failure_reason=row.failure_reason,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _to_model(job: ProcessingJob) -> ProcessingJobModel:
    return ProcessingJobModel(
        id=job.id,
        job_type=job.job_type.value,
        priority=int(job.priority),
        status=job.status.value,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        payload=dict(job.payload),
        scheduled_at=job.scheduled_at,
        lease_expires_at=job.lease_expires_at,
        last_heartbeat_at=job.last_heartbeat_at,
        failure_reason=job.failure_reason,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
