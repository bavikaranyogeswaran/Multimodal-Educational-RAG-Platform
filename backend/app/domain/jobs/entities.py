"""Background job entity.

A job is the durability wrapper around async work. A worker claims it (acquires an
exclusive lease), then either completes it or fails it. If the attempt limit is reached
the job moves to dead-letter; otherwise it sits as FAILED until requeued by a scheduler.
Heartbeats extend the lease while work is in progress so a crashed worker can be detected
without a fixed timeout that would be too short for slow work.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.errors import IllegalTransitionError, InvariantViolationError


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    id: UUID
    job_type: JobType
    priority: JobPriority
    status: JobStatus
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    payload: Mapping[str, str]
    scheduled_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        for req_name, req_ts in [
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ]:
            if req_ts.tzinfo is None:
                raise InvariantViolationError(
                    f"ProcessingJob.{req_name} must be timezone-aware"
                )
        for opt_name, opt_ts in [
            ("scheduled_at", self.scheduled_at),
            ("lease_expires_at", self.lease_expires_at),
            ("last_heartbeat_at", self.last_heartbeat_at),
        ]:
            if opt_ts is not None and opt_ts.tzinfo is None:
                raise InvariantViolationError(
                    f"ProcessingJob.{opt_name} must be timezone-aware when set"
                )
        if self.attempt_count < 0:
            raise InvariantViolationError(
                f"ProcessingJob.attempt_count must be >= 0, got {self.attempt_count}"
            )
        if self.max_attempts < 1:
            raise InvariantViolationError(
                f"ProcessingJob.max_attempts must be >= 1, got {self.max_attempts}"
            )
        if self.attempt_count > self.max_attempts:
            raise InvariantViolationError(
                f"ProcessingJob.attempt_count ({self.attempt_count}) "
                f"exceeds max_attempts ({self.max_attempts})"
            )
        if self.status is JobStatus.RUNNING and self.lease_expires_at is None:
            raise InvariantViolationError("a RUNNING job must have a lease_expires_at")
        if self.status is not JobStatus.RUNNING and self.lease_expires_at is not None:
            raise InvariantViolationError(
                "lease_expires_at must only be set while the job is RUNNING"
            )
        if self.status in {JobStatus.FAILED, JobStatus.DEAD_LETTER} and not self.failure_reason:
            raise InvariantViolationError(
                f"a {self.status} job must carry a failure_reason"
            )

    def _transition(self, target: JobStatus, **updates: object) -> ProcessingJob:
        if not self.status.can_transition_to(target):
            raise IllegalTransitionError("ProcessingJob", self.status, target)
        return replace(self, status=target, **updates)  # type: ignore[arg-type]

    def claim(self, *, lease_until: datetime, now: datetime) -> ProcessingJob:
        """Acquire the job, starting a new attempt."""
        return self._transition(
            JobStatus.RUNNING,
            attempt_count=self.attempt_count + 1,
            lease_expires_at=lease_until,
            last_heartbeat_at=now,
            failure_reason=None,
            updated_at=now,
        )

    def heartbeat(self, *, lease_until: datetime, now: datetime) -> ProcessingJob:
        """Extend the lease while work is still in progress."""
        if self.status is not JobStatus.RUNNING:
            raise InvariantViolationError(
                f"heartbeat requires a RUNNING job, current status is {self.status}"
            )
        return replace(
            self,
            lease_expires_at=lease_until,
            last_heartbeat_at=now,
            updated_at=now,
        )

    def complete(self, *, now: datetime) -> ProcessingJob:
        """Record successful completion."""
        return self._transition(
            JobStatus.COMPLETED,
            lease_expires_at=None,
            last_heartbeat_at=None,
            updated_at=now,
        )

    def fail(self, *, reason: str, now: datetime) -> ProcessingJob:
        """Record a failed attempt.

        Moves to DEAD_LETTER when this attempt exhausts the budget; otherwise FAILED.
        """
        if not reason.strip():
            raise InvariantViolationError("failure reason must not be blank")
        next_status = (
            JobStatus.DEAD_LETTER
            if self.attempt_count >= self.max_attempts
            else JobStatus.FAILED
        )
        return self._transition(
            next_status,
            lease_expires_at=None,
            last_heartbeat_at=None,
            failure_reason=reason,
            updated_at=now,
        )

    def requeue(self, *, now: datetime) -> ProcessingJob:
        """Return a FAILED job to the queue for another attempt."""
        if self.attempt_count >= self.max_attempts:
            raise InvariantViolationError(
                f"cannot requeue: attempt_count {self.attempt_count} "
                f"has reached max_attempts {self.max_attempts}"
            )
        return self._transition(
            JobStatus.PENDING,
            failure_reason=None,
            updated_at=now,
        )

    def cancel(self, *, now: datetime) -> ProcessingJob:
        """Cancel the job, clearing any lease."""
        return self._transition(
            JobStatus.CANCELLED,
            lease_expires_at=None,
            last_heartbeat_at=None,
            updated_at=now,
        )
