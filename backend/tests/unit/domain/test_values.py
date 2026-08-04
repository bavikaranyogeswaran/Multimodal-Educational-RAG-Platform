"""Value objects — construction invariants and the geometry the ingestion pipeline relies on."""

from __future__ import annotations

import dataclasses

import pytest

from app.domain.errors import InvariantViolationError
from app.domain.values import BoundingBox, HeadingPath, TokenBudget


class TestBoundingBox:
    def test_rejects_zero_or_negative_extent(self) -> None:
        with pytest.raises(InvariantViolationError, match="positive extent"):
            BoundingBox(10, 10, 10, 20)
        with pytest.raises(InvariantViolationError, match="positive extent"):
            BoundingBox(10, 10, 5, 20)

    def test_dimensions(self) -> None:
        box = BoundingBox(10, 20, 40, 60)

        assert box.width == 30
        assert box.height == 40
        assert box.area == 1200

    def test_is_immutable(self) -> None:
        box = BoundingBox(0, 0, 1, 1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            box.x0 = 5  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("other", "expected"),
        [
            (BoundingBox(5, 5, 15, 15), True),  # overlapping
            (BoundingBox(20, 20, 30, 30), False),  # disjoint
            (BoundingBox(10, 0, 20, 10), False),  # edge-to-edge counts as disjoint
        ],
    )
    def test_intersects(self, other: BoundingBox, expected: bool) -> None:
        assert BoundingBox(0, 0, 10, 10).intersects(other) is expected

    def test_iou_of_identical_boxes_is_one(self) -> None:
        box = BoundingBox(0, 0, 10, 10)
        assert box.intersection_over_union(box) == pytest.approx(1.0)

    def test_iou_of_disjoint_boxes_is_zero(self) -> None:
        assert BoundingBox(0, 0, 10, 10).intersection_over_union(
            BoundingBox(50, 50, 60, 60)
        ) == pytest.approx(0.0)

    def test_iou_of_half_overlapping_boxes(self) -> None:
        # Two 10x10 boxes sharing a 5x10 strip: intersection 50, union 150.
        left = BoundingBox(0, 0, 10, 10)
        right = BoundingBox(5, 0, 15, 10)

        assert left.intersection_over_union(right) == pytest.approx(50 / 150)

    def test_iou_is_symmetric(self) -> None:
        a, b = BoundingBox(0, 0, 10, 10), BoundingBox(3, 3, 12, 12)
        assert a.intersection_over_union(b) == pytest.approx(b.intersection_over_union(a))

    def test_expanded_grows_on_every_side(self) -> None:
        grown = BoundingBox(10, 10, 20, 20).expanded(5)
        assert grown == BoundingBox(5, 5, 25, 25)

    def test_merged_contains_both(self) -> None:
        """A figure merged with its caption must enclose both crops."""
        figure = BoundingBox(10, 40, 90, 100)
        caption = BoundingBox(15, 25, 85, 38)

        merged = figure.merged(caption)

        assert merged == BoundingBox(10, 25, 90, 100)
        assert merged.area >= figure.area + caption.area


class TestHeadingPath:
    def test_root_is_empty(self) -> None:
        root = HeadingPath.root()

        assert root.depth == 0
        assert root.leaf is None
        assert str(root) == ""

    def test_rejects_blank_segments(self) -> None:
        with pytest.raises(InvariantViolationError, match="blank"):
            HeadingPath(("Chapter 4", "   "))

    def test_child_extends_without_mutating(self) -> None:
        chapter = HeadingPath(("Chapter 4",))
        section = chapter.child("4.2 Photosynthesis")

        assert section.segments == ("Chapter 4", "4.2 Photosynthesis")
        assert chapter.segments == ("Chapter 4",)

    def test_renders_readably(self) -> None:
        path = HeadingPath(("Chapter 4", "4.2 Photosynthesis", "Limiting factors"))
        assert str(path) == "Chapter 4 > 4.2 Photosynthesis > Limiting factors"

    def test_ancestry(self) -> None:
        chapter = HeadingPath(("Chapter 4",))
        section = chapter.child("4.2")
        other = HeadingPath(("Chapter 5",))

        assert chapter.is_ancestor_of(section)
        assert not section.is_ancestor_of(chapter)
        assert not other.is_ancestor_of(section)
        assert not chapter.is_ancestor_of(chapter)

    def test_truncation(self) -> None:
        path = HeadingPath(("Chapter 4", "4.2", "Limiting factors"))

        assert path.truncated_to(1) == HeadingPath(("Chapter 4",))
        assert path.truncated_to(0) == HeadingPath.root()

        with pytest.raises(InvariantViolationError):
            path.truncated_to(-1)


class TestTokenBudget:
    def test_rejects_non_positive_total(self) -> None:
        with pytest.raises(InvariantViolationError, match="total must be positive"):
            TokenBudget(total=0)

    def test_rejects_overspend_at_construction(self) -> None:
        with pytest.raises(InvariantViolationError, match="exceeds total"):
            TokenBudget(total=100, spent=101)

    def test_allocation_returns_a_new_budget(self) -> None:
        budget = TokenBudget(total=1000)
        after = budget.allocate(400)

        assert after.remaining == 600
        assert budget.remaining == 1000

    def test_allocation_beyond_the_budget_raises(self) -> None:
        """Clamping would build an answer on less evidence than the caller supplied."""
        with pytest.raises(InvariantViolationError, match="only 100 remain"):
            TokenBudget(total=100).allocate(150)

    def test_negative_allocation_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="negative"):
            TokenBudget(total=100).allocate(-10)

    def test_allocate_if_possible_reports_rather_than_raises(self) -> None:
        """The shedding path expects some material not to fit."""
        budget = TokenBudget(total=100, spent=90)

        assert budget.allocate_if_possible(50) is None
        fitted = budget.allocate_if_possible(10)
        assert fitted is not None
        assert fitted.exhausted

    def test_exhausted_budget_fits_nothing(self) -> None:
        budget = TokenBudget(total=100, spent=100)

        assert budget.exhausted
        assert not budget.can_fit(1)
        assert budget.can_fit(0)
