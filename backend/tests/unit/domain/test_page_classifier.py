"""Tests for PageClassifier and PageSignals.

The thresholds under test are the boundary between a nearly free read and one that is
orders of magnitude more expensive, so the tests pin the boundaries themselves rather
than sampling comfortably either side of them. Every threshold is exercised at the value
exactly, one step below and one step above.

Fixed local thresholds are used rather than the configured defaults: the defaults are
calibration values expected to move, and a test that moves with them would stop testing
the rule and start restating the setting.
"""

from __future__ import annotations

import pytest

from app.domain.documents.page_classifier import PageClassifier, PageSignals
from app.domain.enums import PageKind
from app.domain.errors import InvariantViolationError

_MIN_CHARS = 50
_TEXT_COVERAGE = 0.10
_IMAGE_COVERAGE = 0.15
_VECTORS = 400

_EPSILON = 0.001


def _classifier() -> PageClassifier:
    return PageClassifier(
        min_native_characters=_MIN_CHARS,
        native_text_coverage_threshold=_TEXT_COVERAGE,
        image_coverage_threshold=_IMAGE_COVERAGE,
        complex_vector_drawing_threshold=_VECTORS,
    )


def _signals(
    *,
    chars: int = 0,
    text: float = 0.0,
    image: float = 0.0,
    vectors: int = 0,
) -> PageSignals:
    return PageSignals(
        native_character_count=chars,
        text_area_ratio=text,
        image_area_ratio=image,
        vector_drawing_count=vectors,
    )


# Signal sets that clearly satisfy or clearly fail each condition, so a test about one
# threshold is not accidentally decided by another.
_STRONG_TEXT = {"chars": 2000, "text": 0.55}
_NO_TEXT = {"chars": 0, "text": 0.0}
_STRONG_IMAGE = {"image": 0.80}
_NO_IMAGE = {"image": 0.0}


# ---------------------------------------------------------------------------
# The four kinds
# ---------------------------------------------------------------------------


class TestTheFourKinds:
    def test_text_and_no_images_is_native_text(self) -> None:
        result = _classifier().classify(_signals(**_STRONG_TEXT, **_NO_IMAGE))
        assert result is PageKind.NATIVE_TEXT

    def test_images_and_no_text_is_scanned(self) -> None:
        result = _classifier().classify(_signals(**_NO_TEXT, **_STRONG_IMAGE))
        assert result is PageKind.SCANNED

    def test_text_and_images_together_is_mixed(self) -> None:
        result = _classifier().classify(_signals(**_STRONG_TEXT, **_STRONG_IMAGE))
        assert result is PageKind.MIXED

    def test_dense_vector_drawings_is_complex(self) -> None:
        result = _classifier().classify(_signals(**_STRONG_TEXT, vectors=_VECTORS + 100))
        assert result is PageKind.COMPLEX

    def test_every_kind_is_reachable(self) -> None:
        """No branch is dead — a rule nothing can reach is a rule nobody maintains."""
        classifier = _classifier()
        produced = {
            classifier.classify(_signals(**_STRONG_TEXT, **_NO_IMAGE)),
            classifier.classify(_signals(**_NO_TEXT, **_STRONG_IMAGE)),
            classifier.classify(_signals(**_STRONG_TEXT, **_STRONG_IMAGE)),
            classifier.classify(_signals(vectors=_VECTORS)),
        }
        assert produced == set(PageKind)


# ---------------------------------------------------------------------------
# Threshold boundaries
# ---------------------------------------------------------------------------


class TestTextCoverageBoundary:
    def test_exactly_at_the_threshold_counts_as_text(self) -> None:
        result = _classifier().classify(
            _signals(chars=2000, text=_TEXT_COVERAGE, **_STRONG_IMAGE)
        )
        assert result is PageKind.MIXED

    def test_just_below_the_threshold_does_not(self) -> None:
        result = _classifier().classify(
            _signals(chars=2000, text=_TEXT_COVERAGE - _EPSILON, **_STRONG_IMAGE)
        )
        assert result is PageKind.SCANNED

    def test_just_above_the_threshold_counts_as_text(self) -> None:
        result = _classifier().classify(
            _signals(chars=2000, text=_TEXT_COVERAGE + _EPSILON, **_STRONG_IMAGE)
        )
        assert result is PageKind.MIXED


class TestCharacterCountBoundary:
    def test_exactly_at_the_minimum_counts_as_text(self) -> None:
        result = _classifier().classify(
            _signals(chars=_MIN_CHARS, text=0.55, **_STRONG_IMAGE)
        )
        assert result is PageKind.MIXED

    def test_one_character_short_does_not(self) -> None:
        result = _classifier().classify(
            _signals(chars=_MIN_CHARS - 1, text=0.55, **_STRONG_IMAGE)
        )
        assert result is PageKind.SCANNED

    def test_generous_coverage_cannot_rescue_an_empty_text_layer(self) -> None:
        """A layer covering the page while holding nothing is what scanners emit."""
        result = _classifier().classify(_signals(chars=3, text=0.95, **_STRONG_IMAGE))
        assert result is PageKind.SCANNED

    def test_many_characters_cannot_rescue_negligible_coverage(self) -> None:
        """A dense caption under a full-page image is not a readable page."""
        result = _classifier().classify(_signals(chars=5000, text=0.02, **_STRONG_IMAGE))
        assert result is PageKind.SCANNED


class TestImageCoverageBoundary:
    def test_exactly_at_the_threshold_counts_as_images(self) -> None:
        result = _classifier().classify(_signals(**_STRONG_TEXT, image=_IMAGE_COVERAGE))
        assert result is PageKind.MIXED

    def test_just_below_the_threshold_is_decoration(self) -> None:
        result = _classifier().classify(
            _signals(**_STRONG_TEXT, image=_IMAGE_COVERAGE - _EPSILON)
        )
        assert result is PageKind.NATIVE_TEXT

    def test_just_above_the_threshold_counts_as_images(self) -> None:
        result = _classifier().classify(
            _signals(**_STRONG_TEXT, image=_IMAGE_COVERAGE + _EPSILON)
        )
        assert result is PageKind.MIXED


class TestVectorDrawingBoundary:
    def test_exactly_at_the_threshold_is_complex(self) -> None:
        result = _classifier().classify(_signals(**_STRONG_TEXT, vectors=_VECTORS))
        assert result is PageKind.COMPLEX

    def test_one_below_the_threshold_is_not(self) -> None:
        result = _classifier().classify(_signals(**_STRONG_TEXT, vectors=_VECTORS - 1))
        assert result is PageKind.NATIVE_TEXT

    def test_complex_outranks_every_other_signal(self) -> None:
        """Dense line work is difficult however good the rest of the page looks."""
        result = _classifier().classify(
            _signals(**_STRONG_TEXT, **_STRONG_IMAGE, vectors=_VECTORS)
        )
        assert result is PageKind.COMPLEX


# ---------------------------------------------------------------------------
# Degenerate pages
# ---------------------------------------------------------------------------


class TestDegeneratePages:
    def test_a_blank_page_classifies_rather_than_raising(self) -> None:
        assert _classifier().classify(PageSignals.blank()) is PageKind.NATIVE_TEXT

    def test_a_blank_page_is_not_sent_for_recognition(self) -> None:
        """Nothing is on it, so the expensive path would only confirm that."""
        kind = _classifier().classify(PageSignals.blank())
        assert kind is not PageKind.SCANNED
        assert kind is not PageKind.COMPLEX

    def test_a_fully_covered_page_is_accepted(self) -> None:
        result = _classifier().classify(
            _signals(chars=9000, text=1.0, image=1.0, vectors=0)
        )
        assert result is PageKind.MIXED

    def test_classification_is_stateless(self) -> None:
        """The same page classifies the same way regardless of what came before it."""
        classifier = _classifier()
        scanned = _signals(**_NO_TEXT, **_STRONG_IMAGE)
        first = classifier.classify(scanned)
        classifier.classify(_signals(**_STRONG_TEXT, vectors=_VECTORS + 1))
        assert classifier.classify(scanned) is first


# ---------------------------------------------------------------------------
# PageSignals validation
# ---------------------------------------------------------------------------


class TestPageSignalsValidation:
    @pytest.mark.parametrize("ratio", [-0.01, 1.01, 2.0, -1.0])
    def test_text_area_ratio_must_be_a_share_of_the_page(self, ratio: float) -> None:
        with pytest.raises(InvariantViolationError):
            _signals(text=ratio)

    @pytest.mark.parametrize("ratio", [-0.01, 1.01, 2.0, -1.0])
    def test_image_area_ratio_must_be_a_share_of_the_page(self, ratio: float) -> None:
        with pytest.raises(InvariantViolationError):
            _signals(image=ratio)

    def test_character_count_cannot_be_negative(self) -> None:
        with pytest.raises(InvariantViolationError):
            _signals(chars=-1)

    def test_vector_drawing_count_cannot_be_negative(self) -> None:
        with pytest.raises(InvariantViolationError):
            _signals(vectors=-1)

    @pytest.mark.parametrize("ratio", [0.0, 1.0])
    def test_the_extremes_of_the_range_are_valid(self, ratio: float) -> None:
        assert _signals(text=ratio, image=ratio).text_area_ratio == ratio

    def test_signals_are_immutable(self) -> None:
        signals = _signals(chars=100, text=0.5)
        with pytest.raises(AttributeError):
            signals.native_character_count = 200  # type: ignore[misc]
