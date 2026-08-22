"""Tests for reading the label at the front of a caption.

The cases are drawn from how textbooks actually number things: sectioned numbers,
appendix letters, sibling suffixes, and the abbreviations that appear more often than
the full words. The negative cases matter as much — "Table of contents" is not a table.
"""

from __future__ import annotations

import pytest

from app.domain.documents.caption_label import (
    CaptionLabel,
    contains_caption_label,
    has_caption_label,
    labels_kind,
    parse_caption_label,
)
from app.domain.enums import ElementType


class TestKind:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Figure 1: A loss curve", ElementType.FIGURE),
            ("Fig. 1", ElementType.FIGURE),
            ("Fig 1", ElementType.FIGURE),
            ("Table 1", ElementType.TABLE),
            ("Tbl. 1", ElementType.TABLE),
            ("Chart 1", ElementType.CHART),
            ("Diagram 1", ElementType.DIAGRAM),
        ],
    )
    def test_it_reads_the_kind(self, text: str, expected: ElementType) -> None:
        label = parse_caption_label(text)
        assert label is not None
        assert label.kind is expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Plate 4", ElementType.FIGURE),
            ("Exhibit 2", ElementType.FIGURE),
            ("Scheme 3", ElementType.DIAGRAM),
        ],
    )
    def test_older_names_read_as_what_they_mean(self, text: str, expected: ElementType) -> None:
        # Refusing these would leave the object unnumbered rather than correctly named.
        label = parse_caption_label(text)
        assert label is not None
        assert label.kind is expected

    def test_it_is_case_insensitive(self) -> None:
        assert parse_caption_label("TABLE 1") == CaptionLabel(ElementType.TABLE, "1")
        assert parse_caption_label("table 1") == CaptionLabel(ElementType.TABLE, "1")


class TestNumber:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Table 1", "1"),
            ("Table 4.2", "4.2"),
            ("Table 12.3.1", "12.3.1"),
            ("Table 4-2", "4-2"),
            ("Chart 2b", "2b"),
            ("Table A.1", "A.1"),
        ],
    )
    def test_it_reads_the_number(self, text: str, expected: str) -> None:
        label = parse_caption_label(text)
        assert label is not None
        assert label.number == expected

    def test_the_number_is_kept_as_the_document_wrote_it(self) -> None:
        # "4.2" and "4-2" are different on the page, so they stay different here — a
        # student typing what they see should match what was printed.
        assert parse_caption_label("Table 4-2") != parse_caption_label("Table 4.2")

    def test_a_trailing_colon_is_not_part_of_the_number(self) -> None:
        label = parse_caption_label("Table 4.2: Properties of metals")
        assert label is not None
        assert label.number == "4.2"

    def test_a_trailing_full_stop_is_not_part_of_the_number(self) -> None:
        label = parse_caption_label("Table 1. Accuracy by run")
        assert label is not None
        assert label.number == "1"


class TestNotALabel:
    @pytest.mark.parametrize(
        "text",
        [
            "Table of contents",
            "Figure it out in three steps",
            "The table below shows the results",
            "Charting a course",
            "",
            "   ",
        ],
    )
    def test_a_line_without_a_number_is_not_a_label(self, text: str) -> None:
        assert parse_caption_label(text) is None

    def test_a_label_must_lead_the_line(self) -> None:
        # A sentence mentioning a table is not that table's caption.
        assert parse_caption_label("As shown in Table 3, accuracy improved") is None

    def test_an_unrelated_word_is_not_a_label(self) -> None:
        assert parse_caption_label("Section 4.2") is None


class TestHasCaptionLabel:
    def test_it_reports_a_label(self) -> None:
        assert has_caption_label("Figure 4.2: Loss curve") is True

    def test_it_reports_the_absence_of_one(self) -> None:
        assert has_caption_label("The results were encouraging") is False


class TestLabelsKind:
    def test_it_matches_the_named_kind(self) -> None:
        assert labels_kind("Table 1: Accuracy", ElementType.TABLE) is True

    def test_it_rejects_a_different_kind(self) -> None:
        # Attaching a figure's caption to a table would describe the wrong thing.
        assert labels_kind("Figure 1: Loss curve", ElementType.TABLE) is False

    def test_it_rejects_a_line_with_no_label(self) -> None:
        assert labels_kind("The results were encouraging", ElementType.TABLE) is False


class TestRendering:
    def test_a_label_reads_back_the_way_a_document_writes_it(self) -> None:
        assert str(CaptionLabel(ElementType.TABLE, "4.2")) == "Table 4.2"
        assert str(CaptionLabel(ElementType.FIGURE, "1")) == "Figure 1"


class TestContainsCaptionLabel:
    """Whether a passage still carries the caption that says what it is about.

    A different question from the others: not "is this line a caption" but "did this
    passage keep its own". A table separated from its caption is a grid of numbers with
    column headings and no subject.
    """

    def test_it_finds_a_label_on_a_later_line(self) -> None:
        text = "Metal Aluminium, Density 2.70.\nTable 4.2: Properties of metals"
        assert contains_caption_label(text, ElementType.TABLE) is True

    def test_it_finds_a_label_on_the_first_line(self) -> None:
        text = "Table 1: Accuracy by run\nRun 1, Accuracy 0.91."
        assert contains_caption_label(text, ElementType.TABLE) is True

    def test_a_passage_with_no_caption_reports_none(self) -> None:
        text = "Metal Aluminium, Density 2.70.\nMetal Iron, Density 7.87."
        assert contains_caption_label(text, ElementType.TABLE) is False

    def test_a_figures_caption_does_not_count_for_a_table(self) -> None:
        text = "Run 1, Accuracy 0.91.\nFigure 2: Loss curve"
        assert contains_caption_label(text, ElementType.TABLE) is False

    def test_a_mention_mid_line_does_not_count(self) -> None:
        # The label has to lead its line. A sentence referring to a table elsewhere is
        # not this passage's caption.
        text = "The values here match those in Table 3 on the previous page."
        assert contains_caption_label(text, ElementType.TABLE) is False

    def test_an_appendix_number_is_recognised(self) -> None:
        # The pattern this replaced required a digit immediately after the word, so
        # "Table A.1" read as carrying no caption at all.
        assert contains_caption_label("Table A.1: Constants", ElementType.TABLE) is True
