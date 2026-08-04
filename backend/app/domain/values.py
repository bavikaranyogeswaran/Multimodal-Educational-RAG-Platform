"""Value objects.

Immutable, compared by value, and validated at construction — an invalid one cannot be
brought into existence, so nothing downstream has to check.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Self

from app.domain.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A rectangle on a page, in PDF user-space points with the origin at bottom-left.

    Carries no page number: a box is a region, and which page it is on belongs to whatever
    owns the box. Keeping them separate avoids two sources of truth for the same fact.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise InvariantViolationError(
                f"BoundingBox must have positive extent, got "
                f"({self.x0}, {self.y0}, {self.x1}, {self.y1})"
            )

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def intersects(self, other: BoundingBox) -> bool:
        return not (
            self.x1 <= other.x0 or other.x1 <= self.x0 or self.y1 <= other.y0 or other.y1 <= self.y0
        )

    def intersection_over_union(self, other: BoundingBox) -> float:
        """Overlap ratio, used to associate captions with the figures they belong to.

        Written once here rather than three times at the call sites that need it.
        """
        if not self.intersects(other):
            return 0.0

        overlap_width = min(self.x1, other.x1) - max(self.x0, other.x0)
        overlap_height = min(self.y1, other.y1) - max(self.y0, other.y0)
        intersection = overlap_width * overlap_height
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0

    def expanded(self, margin: float) -> BoundingBox:
        """Grow the box on every side, for cropping with a little surrounding context."""
        return BoundingBox(
            self.x0 - margin,
            self.y0 - margin,
            self.x1 + margin,
            self.y1 + margin,
        )

    def merged(self, other: BoundingBox) -> BoundingBox:
        """The smallest box containing both — a figure together with its caption."""
        return BoundingBox(
            min(self.x0, other.x0),
            min(self.y0, other.y0),
            max(self.x1, other.x1),
            max(self.y1, other.y1),
        )


@dataclass(frozen=True, slots=True)
class HeadingPath:
    """Where a piece of content sits in a document's section hierarchy.

    Retained through chunking so a chunk knows which chapter and section it came from,
    which is what lets a retrieved fragment be presented with its context rather than as
    an orphaned paragraph.
    """

    segments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not segment.strip() for segment in self.segments):
            raise InvariantViolationError("HeadingPath segments must not be blank")

    @classmethod
    def root(cls) -> Self:
        return cls(())

    @property
    def depth(self) -> int:
        return len(self.segments)

    @property
    def leaf(self) -> str | None:
        return self.segments[-1] if self.segments else None

    def child(self, heading: str) -> HeadingPath:
        """The path one level deeper."""
        return HeadingPath((*self.segments, heading))

    def truncated_to(self, depth: int) -> HeadingPath:
        if depth < 0:
            raise InvariantViolationError("depth must not be negative")
        return HeadingPath(self.segments[:depth])

    def is_ancestor_of(self, other: HeadingPath) -> bool:
        return self.depth < other.depth and other.segments[: self.depth] == self.segments

    def __str__(self) -> str:
        return " > ".join(self.segments)


@dataclass(frozen=True, slots=True)
class UntrustedText:
    """Text that came out of an uploaded document.

    A student's PDF can contain anything, including sentences addressed to the model. That
    text must reach a prompt as *evidence to be read*, never as instructions to be obeyed,
    and the reliable way to ensure it is to make its provenance part of its type rather
    than a rule people remember.

    The safeguard is that `__str__` does not return the content. Interpolating one of these
    into a prompt template by accident yields a harmless placeholder rather than whatever
    the document author wrote, so the mistake is visible in output instead of silent. Code
    that genuinely needs the characters asks for `.value`, and that call site is then an
    explicit acknowledgement of what it is handling.
    """

    value: str

    def __len__(self) -> int:
        return len(self.value)

    def __bool__(self) -> bool:
        return bool(self.value.strip())

    def __str__(self) -> str:
        return f"<untrusted text, {len(self.value)} chars>"

    def __repr__(self) -> str:
        return f"UntrustedText(<{len(self.value)} chars>)"

    def is_blank(self) -> bool:
        return not self.value.strip()

    def truncated(self, limit: int) -> UntrustedText:
        if limit < 0:
            raise InvariantViolationError("truncation limit must not be negative")
        return UntrustedText(self.value[:limit])


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """A fixed allowance and how much of it has been spent.

    The context builder owns allocation and drops low-priority material when the budget
    runs out. Modelling that as a value rather than a running integer means an overspend
    is a raised error at the point it happens, not a provider rejection much later.
    """

    total: int
    spent: int = 0

    def __post_init__(self) -> None:
        if self.total <= 0:
            raise InvariantViolationError(f"TokenBudget.total must be positive, got {self.total}")
        if self.spent < 0:
            raise InvariantViolationError(
                f"TokenBudget.spent must not be negative, got {self.spent}"
            )
        if self.spent > self.total:
            raise InvariantViolationError(
                f"TokenBudget spent {self.spent} exceeds total {self.total}"
            )

    @property
    def remaining(self) -> int:
        return self.total - self.spent

    @property
    def exhausted(self) -> bool:
        return self.remaining == 0

    def can_fit(self, tokens: int) -> bool:
        return tokens <= self.remaining

    def allocate(self, tokens: int) -> TokenBudget:
        """Spend part of the budget, returning the reduced budget.

        Raises rather than clamping: silently truncating evidence would produce an answer
        built on less than the caller believes it supplied.
        """
        if tokens < 0:
            raise InvariantViolationError("cannot allocate a negative number of tokens")
        if not self.can_fit(tokens):
            raise InvariantViolationError(
                f"cannot allocate {tokens} tokens, only {self.remaining} remain of {self.total}"
            )
        return replace(self, spent=self.spent + tokens)

    def allocate_if_possible(self, tokens: int) -> TokenBudget | None:
        """Spend if it fits, otherwise report that it does not.

        For the shedding path, where not fitting is an expected outcome rather than a bug.
        """
        return self.allocate(tokens) if self.can_fit(tokens) else None
