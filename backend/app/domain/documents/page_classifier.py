"""Decide how a page must be read, before any extraction is attempted.

The decision is worth making separately because the ways of reading a page differ in cost
by orders of magnitude. Pulling a text layer is nearly free; optical recognition is slow;
the vision-language model is slow enough that it has to stay a rare exception rather than
a fallback anything can reach. Choosing per page, from cheap measurements, is what keeps
the expensive paths on the pages that actually need them.

Classification is pure and rule-based, in the same shape as the query classifier: signals
are gathered by whatever can see the file, and the decision is made here where it can be
read and tested without one. Thresholds are supplied by the caller rather than written in,
because they are calibration values and calibration values that live in code cannot be
calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import PageKind
from app.domain.invariants import require_non_negative, require_within


@dataclass(frozen=True, slots=True)
class PageSignals:
    """Cheap measurements of one page, taken before deciding how to read it.

    Areas are expressed as a share of the page rather than absolutely, so the same
    thresholds hold for any page size — a figure occupying a third of a page means the
    same thing whether the page is A4 or a foldout.
    """

    #: Characters recoverable from the embedded text layer.
    native_character_count: int
    #: Share of the page covered by the bounding boxes of that text, 0 to 1.
    text_area_ratio: float
    #: Share of the page covered by embedded images, 0 to 1.
    image_area_ratio: float
    #: Lines, curves and rectangles drawn as vectors rather than placed as an image.
    vector_drawing_count: int

    def __post_init__(self) -> None:
        require_non_negative(self.native_character_count, "PageSignals.native_character_count")
        require_non_negative(self.vector_drawing_count, "PageSignals.vector_drawing_count")
        require_within(self.text_area_ratio, "PageSignals.text_area_ratio", low=0.0, high=1.0)
        require_within(self.image_area_ratio, "PageSignals.image_area_ratio", low=0.0, high=1.0)

    @classmethod
    def blank(cls) -> PageSignals:
        """A page with nothing measurable on it."""
        return cls(
            native_character_count=0,
            text_area_ratio=0.0,
            image_area_ratio=0.0,
            vector_drawing_count=0,
        )


class PageClassifier:
    """Assign a `PageKind` from page signals.

    Rules are evaluated in order and the first match wins, so the ordering below is the
    policy and not an implementation detail.

    This is the initial rule set, and it decides from what can be measured before any
    layout analysis has run. Column structure, rotation and table density are further
    reasons a page can be too difficult for ordinary recognition, and they become
    available once reading-order resolution exists — at which point `COMPLEX` should be
    revisited rather than left as it stands here.
    """

    def __init__(
        self,
        *,
        min_native_characters: int,
        native_text_coverage_threshold: float,
        image_coverage_threshold: float,
        complex_vector_drawing_threshold: int,
    ) -> None:
        self._min_native_characters = min_native_characters
        self._native_text_coverage_threshold = native_text_coverage_threshold
        self._image_coverage_threshold = image_coverage_threshold
        self._complex_vector_drawing_threshold = complex_vector_drawing_threshold

    def classify(self, signals: PageSignals) -> PageKind:
        # Dense vector line work — schematics, engineering drawings, heavily ruled
        # tables. Checked first because a page like this is difficult regardless of how
        # good its text layer is: the text layer holds the labels and none of the
        # structure connecting them, so reading it alone produces a list of words in
        # roughly the wrong order.
        if signals.vector_drawing_count >= self._complex_vector_drawing_threshold:
            return PageKind.COMPLEX

        has_text_layer = self._has_usable_text_layer(signals)
        has_images = signals.image_area_ratio >= self._image_coverage_threshold

        # Images and no text to go with them: whatever the page says is inside the
        # image, and only recognition will get it out.
        if not has_text_layer and has_images:
            return PageKind.SCANNED

        # Both, so neither alone is the whole page — the text layer is read directly and
        # the image regions are recognised separately.
        if has_text_layer and has_images:
            return PageKind.MIXED

        # Everything else reads from the text layer, which includes pages that are
        # nearly empty. A blank page classifies as native text rather than scanned
        # because there is nothing on it to recognise, and sending it for recognition
        # would spend the expensive path to confirm it is still blank.
        return PageKind.NATIVE_TEXT

    def _has_usable_text_layer(self, signals: PageSignals) -> bool:
        """Whether the embedded text is worth reading rather than merely present.

        Both conditions are required because either alone is fooled. A page can carry a
        text layer that covers it generously and holds almost nothing — some scanners
        emit one per page whether or not recognition found anything — and a page can
        hold plenty of characters in a caption or footer while the body of it is an
        image.
        """
        return (
            signals.native_character_count >= self._min_native_characters
            and signals.text_area_ratio >= self._native_text_coverage_threshold
        )
