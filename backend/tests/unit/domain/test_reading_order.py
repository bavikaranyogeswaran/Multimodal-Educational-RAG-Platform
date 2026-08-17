"""Tests for ReadingOrderResolver.

Ordering is asserted on synthetic boxes rather than through a PDF, because the property
under test is geometric and a PDF adds nothing to it but a way for the test to fail for
unrelated reasons. The parser tests cover the same behaviour against real files.

The failure this exists to prevent is specific and silent: on a two-column page, sorting
by vertical position alone interleaves the columns line by line. The result is text that
reads as nonsense and chunks as worse, and nothing downstream can tell it happened.
"""

from __future__ import annotations

import pytest

from app.domain.documents.reading_order import LayoutBox, ReadingOrderResolver
from app.domain.errors import InvariantViolationError

_PAGE_WIDTH = 612.0


def _resolver(**overrides: float) -> ReadingOrderResolver:
    defaults: dict[str, float] = {"min_gutter_width": 24.0, "min_column_width": 90.0}
    return ReadingOrderResolver(**{**defaults, **overrides})  # type: ignore[arg-type]


def _box(left: float, right: float, top: float, height: float = 12.0) -> LayoutBox:
    return LayoutBox(left=left, right=right, top=top, bottom=top + height)


def _left(top: float) -> LayoutBox:
    return _box(72, 290, top)


def _right(top: float) -> LayoutBox:
    return _box(320, 540, top)


def _spanning(top: float, height: float = 20.0) -> LayoutBox:
    return _box(72, 540, top, height)


def _order(boxes: list[LayoutBox]) -> list[int]:
    return _resolver().order(boxes, _PAGE_WIDTH)


class TestSingleColumn:
    def test_boxes_are_ordered_down_the_page(self) -> None:
        boxes = [_spanning(300), _spanning(100), _spanning(200)]
        assert _order(boxes) == [1, 2, 0]

    def test_an_empty_page_orders_to_nothing(self) -> None:
        assert _order([]) == []

    def test_a_single_box_needs_no_decision(self) -> None:
        assert _order([_left(100)]) == [0]

    def test_boxes_at_the_same_height_order_left_to_right(self) -> None:
        boxes = [_box(300, 400, 100), _box(72, 200, 100)]
        assert _order(boxes) == [1, 0]


class TestTwoColumns:
    def test_the_left_column_is_read_before_the_right(self) -> None:
        """The failure this prevents: sorting by height alone gives 0,1,2,3 — one line
        of the left column, one of the right, and so on down the page."""
        boxes = [_left(100), _right(100), _left(120), _right(120)]
        assert _order(boxes) == [0, 2, 1, 3]

    def test_a_whole_column_is_read_before_the_next_begins(self) -> None:
        boxes = [_left(t) for t in (100, 120, 140)] + [_right(t) for t in (100, 120, 140)]
        assert _order(boxes) == [0, 1, 2, 3, 4, 5]

    def test_interleaved_input_still_orders_by_column(self) -> None:
        boxes = [_right(140), _left(100), _right(100), _left(140)]
        assert _order(boxes) == [1, 3, 2, 0]


class TestSpanningContent:
    def test_a_spanning_box_separates_what_is_above_from_what_is_below(self) -> None:
        boxes = [_left(100), _right(100), _spanning(200), _left(300), _right(300)]
        assert _order(boxes) == [0, 1, 2, 3, 4]

    def test_columns_do_not_run_past_a_spanning_box(self) -> None:
        """Without banding, both left-column boxes would be read before either
        right-column one, carrying the reader across the figure and back."""
        boxes = [_left(100), _right(100), _spanning(200), _left(300), _right(300)]
        order = _order(boxes)
        assert order.index(0) < order.index(2) < order.index(3)
        assert order.index(1) < order.index(2)

    def test_a_heading_over_both_columns_is_read_first(self) -> None:
        boxes = [_left(100), _right(100), _spanning(50)]
        assert _order(boxes)[0] == 2

    def test_a_spanning_box_does_not_hide_the_gutter(self) -> None:
        """It physically covers the gap. Counting its width when looking for the gap
        would make a two-column page read as one."""
        boxes = [_left(100), _right(100), _left(120), _right(120), _spanning(50)]
        assert _order(boxes) == [4, 0, 2, 1, 3]


class TestGutterDetection:
    def test_a_narrow_gap_is_not_a_gutter(self) -> None:
        """Ordinary space between words and at line ends is not a column boundary."""
        boxes = [_box(72, 300, 100), _box(310, 540, 100), _box(72, 300, 120)]
        resolver = _resolver(min_gutter_width=24.0)
        assert resolver.find_gutters(boxes) == []

    def test_a_wide_gap_is_a_gutter(self) -> None:
        boxes = [_left(100), _right(100), _left(120), _right(120)]
        assert _resolver().find_gutters(boxes) != []

    def test_a_sliver_beside_a_column_is_not_a_gutter(self) -> None:
        """A narrow strip of content at the edge would otherwise split the page into a
        column and a margin note."""
        boxes = [_box(72, 400, 100), _box(500, 540, 100), _box(72, 400, 120)]
        assert _resolver().find_gutters(boxes) == []

    def test_a_single_column_page_has_no_gutters(self) -> None:
        boxes = [_spanning(t) for t in (100, 120, 140, 160)]
        assert _resolver().find_gutters(boxes) == []

    def test_page_width_must_be_positive(self) -> None:
        with pytest.raises(InvariantViolationError):
            _resolver().order([_left(1), _right(1)], 0.0)


class TestColumnAssignment:
    def test_boxes_are_assigned_by_their_left_edge(self) -> None:
        resolver = _resolver()
        boxes = [_left(100), _right(100), _left(120), _right(120)]
        gutters = resolver.find_gutters(boxes)
        assert resolver.column_of(_left(100), gutters) == 0
        assert resolver.column_of(_right(100), gutters) == 1

    def test_a_box_overhanging_its_column_stays_in_it(self) -> None:
        resolver = _resolver()
        boxes = [_left(100), _right(100), _left(120), _right(120)]
        gutters = resolver.find_gutters(boxes)
        overhanging = _box(72, 330, 140)
        assert resolver.column_of(overhanging, gutters) == 0
