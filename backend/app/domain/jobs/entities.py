"""Background job entity.

A job is the durability wrapper around async work. A worker claims it (acquires an
exclusive lease), then either completes it or fails it. Heartbeats extend the lease while
work is in progress so a crashed worker can be detected without a fixed timeout that would
be too short for slow work.

Failure is not the end of a job unless its attempts are spent. A failed attempt records
when the job becomes eligible again, and the interval grows with each attempt: whatever
went wrong is more likely to still be true a second later than a minute later, and hammering
a provider that is already struggling is how a transient fault becomes a sustained one. Once
the attempts are gone the job dead-letters, which is terminal and deliberate — something has
to stop, and stopping loudly is better than retrying quietly for ever.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from app.domain.enums import JobPriority, JobStatus, JobType
from app.domain.errors import IllegalTransitionError, InvariantViolationError


def backoff_seconds(attempt_count: int, *, base_seconds: int, max_seconds: int) -> int:
    """How long to wait before the attempt after this one.

    Doubles with each attempt already made and stops at the ceiling. Growth is what makes
    a retry useful — a fault that is still present a second later may well be gone a
    minute later — and the ceiling is what stops the last attempt of a long budget being
    scheduled beyond anyone's patience.

    Deliberately without jitter. One worker processes one job at a time here, so there is
    no thundering herd to spread out, and a predictable delay is far easier to reason
    about when reading why a job ran when it did.
    """
    if attempt_count <= 0:
        return base_seconds
    # Shifted rather than raised to a power, so the result is an integer by construction.
    # The exponent is capped first: past a certain attempt count the doubling would build
    # an enormous number that the ceiling below immediately discards.
    doublings = min(attempt_count - 1, 32)
    return min(base_seconds << doublings, max_seconds)


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

    def fail(
        self,
        *,
        reason: str,
        now: datetime,
        backoff_base_seconds: int,
        backoff_max_seconds: int,
    ) -> ProcessingJob:
        """Record a failed attempt, and say when the job may be tried again.

        Moves to DEAD_LETTER when this attempt exhausts the budget; otherwise FAILED with
        a `scheduled_at` in the future. A dead-lettered job carries no schedule, because
        there is nothing left to schedule.

        The backoff bounds are supplied rather than known here: they are calibration
        values, and a domain that hardcoded them could not be recalibrated.
        """
        if not reason.strip():
            raise InvariantViolationError("failure reason must not be blank")

        if self.attempt_count >= self.max_attempts:
            return self._transition(
                JobStatus.DEAD_LETTER,
                lease_expires_at=None,
                last_heartbeat_at=None,
                scheduled_at=None,
                failure_reason=reason,
                updated_at=now,
            )

        return self._transition(
            JobStatus.FAILED,
            lease_expires_at=None,
            last_heartbeat_at=None,
            scheduled_at=now
            + timedelta(
                seconds=backoff_seconds(
                    self.attempt_count,
                    base_seconds=backoff_base_seconds,
                    max_seconds=backoff_max_seconds,
                )
            ),
            failure_reason=reason,
            updated_at=now,
        )

    @property
    def attempts_remain(self) -> bool:
        """Whether another attempt is permitted after the ones already made."""
        return self.attempt_count < self.max_attempts

    def is_retryable_at(self, now: datetime) -> bool:
        """Whether this failed job is ready to be tried again."""
        if self.status is not JobStatus.FAILED or not self.attempts_remain:
            return False
        return self.scheduled_at is None or self.scheduled_at <= now

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
