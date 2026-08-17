"""Put the things found on a page into the order somebody would read them.

A PDF stores marks in whatever order the producer emitted them, which on a multi-column
page is frequently not the order anyone reads. Sorting by vertical position alone fixes
the single-column case and actively breaks the two-column one, interleaving the columns
line by line into text that reads as nonsense and chunks as worse.

Columns are found from the whitespace between them rather than declared, because nothing
in a PDF declares them. Anything wide enough to cross a gutter — a running head, a
full-width figure, a heading over both columns — belongs to neither column and is treated
as a divider: what sits above it is read before it, and what sits below is read after.
That is what keeps a figure in the middle of a page from scrambling the columns around it.

Coordinates here run downward from the top of the page, matching how a page is read and
how layout libraries report positions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.invariants import require_positive

#: How much wider than the median a box may be and still count as column content. A
#: column line varies with its own ragged right edge; something half again as wide as
#: the typical line is spanning rather than wrapping.
_WIDTH_OUTLIER_RATIO = 1.5


@dataclass(frozen=True, slots=True)
class LayoutBox:
    """A rectangle on a page, measured downward from the top."""

    left: float
    right: float
    top: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    def spans(self, gutter: tuple[float, float]) -> bool:
        """Whether this box crosses the given empty vertical strip."""
        start, end = gutter
        return self.left < start and self.right > end


class ReadingOrderResolver:
    """Order boxes down a page, respecting columns where there are any."""

    def __init__(self, *, min_gutter_width: float, min_column_width: float) -> None:
        self._min_gutter_width = min_gutter_width
        self._min_column_width = min_column_width

    def order(self, boxes: Sequence[LayoutBox], page_width: float) -> list[int]:
        """Indices of `boxes`, in reading order.

        Indices rather than the boxes themselves, so a caller can carry whatever it
        attached to each box through the reordering without this having to know about it.
        """
        require_positive(page_width, "page_width")
        if len(boxes) < 2:
            return list(range(len(boxes)))

        gutters = self.find_gutters(boxes)
        if not gutters:
            return _sorted_indices(boxes, range(len(boxes)))

        return self._order_in_bands(boxes, gutters)

    def column_of(self, box: LayoutBox, gutters: list[tuple[float, float]]) -> int:
        """Which column a box sits in, counting from the left.

        Public because columns have to be known before lines are grouped into
        paragraphs, not only afterwards: two columns sitting side by side put their
        lines at the same heights, and anything that groups by height alone will weave
        them together into paragraphs that read across the gutter.
        """
        return _column_of(box, gutters)

    # -----------------------------------------------------------------------

    def find_gutters(self, boxes: Sequence[LayoutBox]) -> list[tuple[float, float]]:
        """Empty vertical strips wide enough to separate columns.

        Built by walking the horizontal extents in order and noting where one ends before
        the next begins. A strip only counts if the columns it would create are both
        substantial — otherwise the space beside a short centred title reads as a gutter
        and splits the page into a column and a sliver.

        Boxes far wider than the rest are left out of this measurement. A heading over
        both columns, or a figure across the full measure, physically covers the gutter,
        and counting them would hide the very gap being looked for — a page would be read
        as one column purely because something on it spanned two.
        """
        candidates = _typical_width(boxes)
        if len(candidates) < 2:
            return []

        intervals = sorted((box.left, box.right) for box in candidates)
        gutters: list[tuple[float, float]] = []
        reach = intervals[0][1]
        for left, right in intervals[1:]:
            if left - reach >= self._min_gutter_width:
                gutters.append((reach, left))
            reach = max(reach, right)

        content_start = min(box.left for box in candidates)
        content_end = max(box.right for box in candidates)
        return [
            (start, end)
            for start, end in gutters
            if start - content_start >= self._min_column_width
            and content_end - end >= self._min_column_width
        ]

    def _order_in_bands(
        self, boxes: Sequence[LayoutBox], gutters: list[tuple[float, float]]
    ) -> list[int]:
        """Read down the page, taking each band of columns in turn.

        A band is the run of column content between two dividers. Within a band every
        column is read to its end before the next begins; the dividers themselves are
        read where they sit.
        """
        order: list[int] = []
        band: list[int] = []

        for index in sorted(range(len(boxes)), key=lambda i: (boxes[i].top, boxes[i].left)):
            if any(boxes[index].spans(gutter) for gutter in gutters):
                order.extend(_sorted_indices(boxes, band, gutters))
                order.append(index)
                band = []
            else:
                band.append(index)

        order.extend(_sorted_indices(boxes, band, gutters))
        return order


def _sorted_indices(
    boxes: Sequence[LayoutBox],
    indices: Sequence[int] | range,
    gutters: list[tuple[float, float]] | None = None,
) -> list[int]:
    """Indices ordered by column first, then down the page."""
    if gutters is None:
        return sorted(indices, key=lambda i: (boxes[i].top, boxes[i].left))
    return sorted(
        indices,
        key=lambda i: (_column_of(boxes[i], gutters), boxes[i].top, boxes[i].left),
    )


def _typical_width(boxes: Sequence[LayoutBox]) -> list[LayoutBox]:
    """Boxes that are not conspicuously wider than the rest.

    Compared against the median rather than the mean, so a handful of full-width items
    cannot drag the reference up to include themselves. On a page where everything is a
    similar width — which is every single-column page — nothing is excluded and the
    result is the whole set.
    """
    widths = sorted(box.width for box in boxes)
    median = widths[len(widths) // 2]
    if median <= 0:
        return list(boxes)
    return [box for box in boxes if box.width <= median * _WIDTH_OUTLIER_RATIO]


def _column_of(box: LayoutBox, gutters: list[tuple[float, float]]) -> int:
    """Which column a box sits in, counting from the left.

    Decided by the box's left edge against each gutter, so a box that overhangs its
    column slightly still belongs to the one it starts in.
    """
    return sum(1 for start, _ in gutters if box.left >= start)
