"""Tests for ElementClassifier.

The rule that matters most here is that every judgement is made relative to the page. A
classifier that reads absolute type sizes works on the documents it was tuned against and
quietly fails on a slide deck, a large-print edition, or anything typeset unusually — so
the relative-size behaviour is pinned from several directions rather than sampled once.

Fixed local thresholds are used rather than the configured defaults, for the same reason
as in the page classifier tests: the defaults are calibration values expected to move,
and a test that moves with them stops testing the rule.
"""

from __future__ import annotations

import pytest

from app.domain.documents.element_classifier import ElementClassifier, ElementSignals
from app.domain.enums import ElementType
from app.domain.errors import InvariantViolationError

_HEADING_RATIO = 1.15
_HEADING_MAX_LINES = 3
_FORMULA_RATIO = 0.25

_BODY = 10.0


def _classifier() -> ElementClassifier:
    return ElementClassifier(
        heading_size_ratio=_HEADING_RATIO,
        heading_max_lines=_HEADING_MAX_LINES,
        formula_symbol_ratio=_FORMULA_RATIO,
    )


def _signals(
    text: str,
    *,
    size: float = _BODY,
    body: float = _BODY,
    bold: bool = False,
    lines: int = 1,
) -> ElementSignals:
    return ElementSignals(
        text=text,
        font_size=size,
        page_body_font_size=body,
        is_bold=bold,
        line_count=lines,
    )


def _classify(text: str, **kwargs: object) -> ElementType:
    return _classifier().classify(_signals(text, **kwargs))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------


class TestHeadings:
    def test_larger_than_the_body_reads_as_a_heading(self) -> None:
        assert _classify("Introduction", size=16.0) is ElementType.HEADING

    def test_bold_at_body_size_reads_as_a_heading(self) -> None:
        """Run-in headings are set in the body size and distinguished by weight alone."""
        assert _classify("Introduction", bold=True) is ElementType.HEADING

    def test_body_text_is_not_a_heading(self) -> None:
        assert _classify("This is ordinary prose.") is ElementType.PARAGRAPH

    def test_a_whole_page_of_large_type_yields_no_headings(self) -> None:
        """The signal is being larger than the page, not being large. On a page set
        entirely in 24pt, nothing is set apart."""
        assert _classify("Introduction", size=24.0, body=24.0) is ElementType.PARAGRAPH

    def test_the_same_line_is_a_heading_or_not_depending_on_its_page(self) -> None:
        assert _classify("Introduction", size=16.0, body=10.0) is ElementType.HEADING
        assert _classify("Introduction", size=16.0, body=16.0) is ElementType.PARAGRAPH

    def test_a_long_run_is_prose_however_it_is_set(self) -> None:
        """Length is what separates a title from an emphasised passage."""
        result = _classify(
            "A great deal of emphasised text", size=20.0, bold=True, lines=8
        )
        assert result is ElementType.PARAGRAPH

    def test_a_sentence_ending_disqualifies_a_heading(self) -> None:
        assert _classify("This is emphasised.", size=20.0, bold=True) is ElementType.PARAGRAPH

    @pytest.mark.parametrize("ending", [".", "!", "?", ":", ";"])
    def test_every_sentence_ending_disqualifies(self, ending: str) -> None:
        assert _classify(f"Emphasised{ending}", size=20.0) is ElementType.PARAGRAPH


class TestHeadingBoundaries:
    def test_exactly_at_the_size_ratio_is_a_heading(self) -> None:
        assert _classify("Title", size=_BODY * _HEADING_RATIO) is ElementType.HEADING

    def test_just_below_the_size_ratio_is_not(self) -> None:
        assert _classify("Title", size=_BODY * _HEADING_RATIO - 0.01) is ElementType.PARAGRAPH

    def test_exactly_at_the_line_limit_is_still_a_heading(self) -> None:
        result = _classify("A wrapped title", size=16.0, lines=_HEADING_MAX_LINES)
        assert result is ElementType.HEADING

    def test_one_line_beyond_the_limit_is_not(self) -> None:
        result = _classify("A wrapped title", size=16.0, lines=_HEADING_MAX_LINES + 1)
        assert result is ElementType.PARAGRAPH


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------


class TestCaptions:
    @pytest.mark.parametrize(
        "text",
        [
            "Figure 4.2: The backward pass",
            "Fig. 1 shows the network",
            "figure 12 — gradient flow",
            "Table 3: Results",
            "TABLE 10 Summary statistics",
            "Chart 2b: Loss over time",
            "Diagram 7 — architecture",
            "Exhibit 1: Sample output",
        ],
    )
    def test_a_leading_label_reads_as_a_caption(self, text: str) -> None:
        assert _classify(text) is ElementType.CAPTION

    def test_a_caption_beats_the_heading_rules(self) -> None:
        """Captions are frequently bold and short, and would otherwise be promoted."""
        assert _classify("Figure 4.2: The backward pass", size=16.0, bold=True) is (
            ElementType.CAPTION
        )

    def test_a_mention_mid_sentence_is_not_a_caption(self) -> None:
        """Only a label leading the run counts. Prose refers to figures constantly."""
        result = _classify("As shown in Figure 4.2, the gradient decays.")
        assert result is ElementType.PARAGRAPH

    def test_a_label_without_a_number_is_not_a_caption(self) -> None:
        assert _classify("Figures of speech are common") is ElementType.PARAGRAPH


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


class TestLists:
    @pytest.mark.parametrize(
        "text",
        [
            "- first item",
            "• first item",
            "* first item",
            "1. first item",
            "2) first item",
            "(3) first item",
            "a. first item",
            "b) first item",
            "iv. first item",
        ],
    )
    def test_a_leading_marker_reads_as_a_list(self, text: str) -> None:
        assert _classify(text) is ElementType.LIST

    def test_a_list_beats_the_heading_rules(self) -> None:
        assert _classify("- first item", size=16.0, bold=True) is ElementType.LIST

    def test_a_hyphenated_word_does_not_make_a_list(self) -> None:
        assert _classify("well-formed prose here") is ElementType.PARAGRAPH

    def test_a_sentence_starting_with_a_number_is_not_a_list(self) -> None:
        assert _classify("1996 was a notable year.") is ElementType.PARAGRAPH


# ---------------------------------------------------------------------------
# Formulas
# ---------------------------------------------------------------------------


class TestFormulas:
    def test_dense_mathematical_symbols_read_as_a_formula(self) -> None:
        assert _classify("∂λ∇≤∑∫") is ElementType.FORMULA

    def test_prose_mentioning_one_symbol_is_not_a_formula(self) -> None:
        # The alpha is the point: one symbol in a sentence is not an equation.
        result = _classify(
            "The learning rate is denoted α in the equations above."  # noqa: RUF001
        )
        assert result is ElementType.PARAGRAPH

    def test_arithmetic_and_brackets_alone_do_not_make_a_formula(self) -> None:
        """Ordinary prose is full of hyphens and brackets; counting them would make
        every parenthetical into an equation."""
        result = _classify("The result (see above) is well-known - and widely used.")
        assert result is ElementType.PARAGRAPH

    def test_a_formula_beats_the_heading_rules(self) -> None:
        assert _classify("∑∫∂√∇", size=16.0, bold=True) is ElementType.FORMULA


# ---------------------------------------------------------------------------
# Fallback and validation
# ---------------------------------------------------------------------------


class TestFallback:
    def test_plain_prose_is_a_paragraph(self) -> None:
        assert _classify("The algorithm proceeds in two passes.") is ElementType.PARAGRAPH

    def test_empty_text_classifies_rather_than_raising(self) -> None:
        assert _classify("") is ElementType.PARAGRAPH

    def test_whitespace_only_text_classifies_rather_than_raising(self) -> None:
        assert _classify("   \n  ") is ElementType.PARAGRAPH

    def test_classification_is_stateless(self) -> None:
        classifier = _classifier()
        prose = _signals("Ordinary prose here.")
        first = classifier.classify(prose)
        classifier.classify(_signals("Figure 1: something"))
        assert classifier.classify(prose) is first


class TestSignalValidation:
    def test_font_size_must_be_positive(self) -> None:
        with pytest.raises(InvariantViolationError):
            _signals("text", size=0.0)

    def test_page_body_font_size_must_be_positive(self) -> None:
        with pytest.raises(InvariantViolationError):
            _signals("text", body=0.0)

    def test_line_count_cannot_be_negative(self) -> None:
        with pytest.raises(InvariantViolationError):
            _signals("text", lines=-1)

    def test_size_ratio_compares_against_the_page(self) -> None:
        assert _signals("t", size=20.0, body=10.0).size_ratio == pytest.approx(2.0)
