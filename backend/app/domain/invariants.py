"""Validation helpers shared by entities and value objects.

Every entity checks the same handful of things — a name that is not blank, a page number
that starts at one, a timestamp that knows its own offset. Writing them once means the
error messages are consistent and the checks cannot quietly diverge.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.errors import InvariantViolationError


def require_non_blank(value: str, field: str) -> str:
    """A required string that is present but empty is almost always a bug upstream."""
    if not value or not value.strip():
        raise InvariantViolationError(f"{field} must not be blank")
    return value


def require_positive(value: int | float, field: str) -> None:
    if value <= 0:
        raise InvariantViolationError(f"{field} must be positive, got {value}")


def require_non_negative(value: int | float, field: str) -> None:
    if value < 0:
        raise InvariantViolationError(f"{field} must not be negative, got {value}")


def require_within(value: float, field: str, *, low: float, high: float) -> None:
    if not low <= value <= high:
        raise InvariantViolationError(f"{field} must be between {low} and {high}, got {value}")


def require_timezone_aware(value: datetime, field: str) -> None:
    """Reject naive timestamps.

    A naive datetime is not merely imprecise, it is ambiguous: the same value means
    different instants depending on where it is read. Lease expiry, memory validity
    windows and exam countdowns all compare timestamps, and a comparison between a naive
    and an aware value raises at the worst possible moment rather than at construction.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvariantViolationError(f"{field} must be timezone-aware, got {value!r}")


def require_ordered(
    earlier: datetime | None,
    later: datetime | None,
    *,
    earlier_field: str,
    later_field: str,
) -> None:
    """Reject a pair of timestamps that runs backwards, when both are present."""
    if earlier is not None and later is not None and later < earlier:
        raise InvariantViolationError(
            f"{later_field} ({later.isoformat()}) precedes {earlier_field} ({earlier.isoformat()})"
        )
