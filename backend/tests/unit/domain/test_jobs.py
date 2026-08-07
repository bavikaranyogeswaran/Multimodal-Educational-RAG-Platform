"""ProcessingJob entity and lifecycle.

Jobs move through a well-defined state machine. The key invariants are:
  - a RUNNING job always holds a lease
  - FAILED and DEAD_LETTER always carry a failure reason
  - claim increments attempt_count; dead-lettering happens when that count reaches the limit
  - heartbeat extends the lease without changing status
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.enums import JobPriority, JobStatus
from app.domain.errors import IllegalTransitionError, InvariantViolationError
from app.domain.jobs.entities import ProcessingJob

from .conftest import LATER, NOW, Builder

LEASE_UNTIL = NOW + timedelta(minutes=5)
MUCH_LATER = LATER + timedelta(minutes=10)


class TestProcessingJobConstruction:
    def test_rejects_a_naive_created_at(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="created_at"):
            make_processing_job(created_at=datetime(2026, 1, 1))  # noqa: DTZ001

    def test_rejects_negative_attempt_count(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="attempt_count"):
            make_processing_job(attempt_count=-1)

    def test_rejects_zero_max_attempts(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="max_attempts"):
            make_processing_job(max_attempts=0)

    def test_rejects_attempt_count_exceeding_max(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="attempt_count"):
            make_processing_job(attempt_count=4, max_attempts=3)

    def test_rejects_running_without_a_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="lease"):
            make_processing_job(status=JobStatus.RUNNING, attempt_count=1)

    def test_rejects_a_lease_on_a_pending_job(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="lease"):
            make_processing_job(
                status=JobStatus.PENDING, lease_expires_at=LEASE_UNTIL
            )

    def test_rejects_failed_without_a_reason(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="failure_reason"):
            make_processing_job(status=JobStatus.FAILED, attempt_count=1)

    def test_rejects_dead_letter_without_a_reason(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        with pytest.raises(InvariantViolationError, match="failure_reason"):
            make_processing_job(
                status=JobStatus.DEAD_LETTER,
                attempt_count=3,
                max_attempts=3,
            )

    def test_pending_job_has_no_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        assert job.lease_expires_at is None

    def test_priority_is_stored(self, make_processing_job: Builder[ProcessingJob]) -> None:
        job = make_processing_job(priority=JobPriority.INTERACTIVE)
        assert job.priority is JobPriority.INTERACTIVE


class TestJobClaim:
    def test_claim_moves_to_running(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        running = job.claim(lease_until=LEASE_UNTIL, now=NOW)
        assert running.status is JobStatus.RUNNING

    def test_claim_sets_the_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        running = job.claim(lease_until=LEASE_UNTIL, now=NOW)
        assert running.lease_expires_at == LEASE_UNTIL

    def test_claim_increments_attempt_count(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job(attempt_count=0)
        running = job.claim(lease_until=LEASE_UNTIL, now=NOW)
        assert running.attempt_count == 1

    def test_claim_sets_last_heartbeat(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        running = job.claim(lease_until=LEASE_UNTIL, now=NOW)
        assert running.last_heartbeat_at == NOW

    def test_claim_does_not_mutate_original(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        job.claim(lease_until=LEASE_UNTIL, now=NOW)
        assert job.status is JobStatus.PENDING

    def test_claim_from_failed_is_illegal(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job(
            status=JobStatus.FAILED,
            attempt_count=1,
            failure_reason="connection timeout",
        )
        with pytest.raises(IllegalTransitionError):
            job.claim(lease_until=LEASE_UNTIL, now=NOW)


class TestJobHeartbeat:
    def test_heartbeat_extends_the_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            lease_expires_at=LEASE_UNTIL,
            last_heartbeat_at=NOW,
        )
        new_lease = LEASE_UNTIL + timedelta(minutes=5)
        refreshed = running.heartbeat(lease_until=new_lease, now=LATER)
        assert refreshed.lease_expires_at == new_lease
        assert refreshed.last_heartbeat_at == LATER
        assert refreshed.status is JobStatus.RUNNING

    def test_heartbeat_on_pending_is_illegal(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        with pytest.raises(InvariantViolationError, match="RUNNING"):
            job.heartbeat(lease_until=LEASE_UNTIL, now=NOW)


class TestJobCompletion:
    def test_complete_moves_to_completed(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            lease_expires_at=LEASE_UNTIL,
        )
        done = running.complete(now=LATER)
        assert done.status is JobStatus.COMPLETED

    def test_complete_clears_the_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            lease_expires_at=LEASE_UNTIL,
        )
        done = running.complete(now=LATER)
        assert done.lease_expires_at is None

    def test_complete_from_pending_is_illegal(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        job = make_processing_job()
        with pytest.raises(IllegalTransitionError):
            job.complete(now=LATER)


class TestJobFailure:
    def test_fail_below_max_moves_to_failed(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            max_attempts=3,
            lease_expires_at=LEASE_UNTIL,
        )
        failed = running.fail(reason="connection timeout", now=LATER)
        assert failed.status is JobStatus.FAILED

    def test_fail_at_max_moves_to_dead_letter(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=3,
            max_attempts=3,
            lease_expires_at=LEASE_UNTIL,
        )
        dead = running.fail(reason="exhausted retries", now=LATER)
        assert dead.status is JobStatus.DEAD_LETTER

    def test_fail_stores_the_reason(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            max_attempts=3,
            lease_expires_at=LEASE_UNTIL,
        )
        failed = running.fail(reason="connection timeout", now=LATER)
        assert failed.failure_reason == "connection timeout"

    def test_fail_clears_the_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            max_attempts=3,
            lease_expires_at=LEASE_UNTIL,
        )
        failed = running.fail(reason="timeout", now=LATER)
        assert failed.lease_expires_at is None

    def test_fail_rejects_blank_reason(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            max_attempts=3,
            lease_expires_at=LEASE_UNTIL,
        )
        with pytest.raises(InvariantViolationError):
            running.fail(reason="  ", now=LATER)


class TestJobRequeue:
    def test_requeue_moves_failed_to_pending(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        failed = make_processing_job(
            status=JobStatus.FAILED,
            attempt_count=1,
            max_attempts=3,
            failure_reason="transient error",
        )
        requeued = failed.requeue(now=LATER)
        assert requeued.status is JobStatus.PENDING

    def test_requeue_clears_failure_reason(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        failed = make_processing_job(
            status=JobStatus.FAILED,
            attempt_count=1,
            max_attempts=3,
            failure_reason="transient error",
        )
        requeued = failed.requeue(now=LATER)
        assert requeued.failure_reason is None

    def test_requeue_blocked_when_attempts_exhausted(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        failed = make_processing_job(
            status=JobStatus.FAILED,
            attempt_count=3,
            max_attempts=3,
            failure_reason="exhausted",
        )
        with pytest.raises(InvariantViolationError, match="max_attempts"):
            failed.requeue(now=LATER)


class TestJobCancellation:
    def test_cancel_pending_job(self, make_processing_job: Builder[ProcessingJob]) -> None:
        job = make_processing_job()
        cancelled = job.cancel(now=LATER)
        assert cancelled.status is JobStatus.CANCELLED

    def test_cancel_running_job_clears_lease(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        running = make_processing_job(
            status=JobStatus.RUNNING,
            attempt_count=1,
            lease_expires_at=LEASE_UNTIL,
        )
        cancelled = running.cancel(now=LATER)
        assert cancelled.status is JobStatus.CANCELLED
        assert cancelled.lease_expires_at is None

    def test_cancel_completed_job_is_illegal(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        done = make_processing_job(status=JobStatus.COMPLETED, attempt_count=1)
        with pytest.raises(IllegalTransitionError):
            done.cancel(now=LATER)

    def test_cancel_already_cancelled_is_illegal(
        self, make_processing_job: Builder[ProcessingJob]
    ) -> None:
        cancelled = make_processing_job(status=JobStatus.CANCELLED, attempt_count=1)
        with pytest.raises(IllegalTransitionError):
            cancelled.cancel(now=LATER)


class TestJobStatusTransitions:
    """The transition table is complete and terminal states are absorbing."""

    def test_pending_can_move_to_running(self) -> None:
        assert JobStatus.PENDING.can_transition_to(JobStatus.RUNNING)

    def test_pending_can_be_cancelled(self) -> None:
        assert JobStatus.PENDING.can_transition_to(JobStatus.CANCELLED)

    def test_running_can_complete(self) -> None:
        assert JobStatus.RUNNING.can_transition_to(JobStatus.COMPLETED)

    def test_running_can_fail(self) -> None:
        assert JobStatus.RUNNING.can_transition_to(JobStatus.FAILED)

    def test_running_can_dead_letter(self) -> None:
        assert JobStatus.RUNNING.can_transition_to(JobStatus.DEAD_LETTER)

    def test_failed_can_be_requeued(self) -> None:
        assert JobStatus.FAILED.can_transition_to(JobStatus.PENDING)

    def test_completed_is_absorbing(self) -> None:
        assert not JobStatus.COMPLETED.can_transition_to(JobStatus.PENDING)
        assert not JobStatus.COMPLETED.can_transition_to(JobStatus.RUNNING)

    def test_cancelled_is_absorbing(self) -> None:
        assert not JobStatus.CANCELLED.can_transition_to(JobStatus.PENDING)

    def test_dead_letter_can_only_be_cancelled(self) -> None:
        assert JobStatus.DEAD_LETTER.can_transition_to(JobStatus.CANCELLED)
        assert not JobStatus.DEAD_LETTER.can_transition_to(JobStatus.PENDING)
