"""Tests for PdfPlumberParser against committed PDF fixtures.

The fixtures are real PDFs, built by `tests/fixtures/pdfs/make_fixtures.py` so their
contents can be read rather than guessed at, and the golden file records exactly what the
parser makes of one of them. A golden file earns its keep by failing on changes nobody
described — a paragraph that regroups, a box that moves, an element that appears — which
is the class of change a targeted assertion is least likely to be looking for.

Identifiers and timestamps are excluded from the snapshot. They differ on every run by
design, and a golden file that has to be regenerated after every run stops being read.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import uuid
from typing import Any

import pytest

from app.domain.documents.element_classifier import ElementClassifier
from app.domain.documents.page_classifier import PageClassifier
from app.domain.documents.reading_order import ReadingOrderResolver
from app.domain.enums import ElementType, PageKind, ProcessingMethod
from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext
from app.infrastructure.parsing.pdfplumber_parser import PdfPlumberParser

_FIXTURES = pathlib.Path(__file__).parents[2] / "fixtures" / "pdfs"
_GOLDEN = _FIXTURES / "native_text_sample.golden.json"

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_DOCUMENT_ID = uuid.uuid4()


def _pdf(name: str) -> bytes:
    return (_FIXTURES / f"{name}.pdf").read_bytes()


def _classifier(**overrides: Any) -> PageClassifier:
    defaults: dict[str, Any] = {
        "min_native_characters": 50,
        "native_text_coverage_threshold": 0.10,
        "image_coverage_threshold": 0.15,
        "complex_vector_drawing_threshold": 400,
    }
    return PageClassifier(**{**defaults, **overrides})


def _element_classifier(**overrides: Any) -> ElementClassifier:
    defaults: dict[str, Any] = {
        "heading_size_ratio": 1.15,
        "heading_max_lines": 3,
        "formula_symbol_ratio": 0.25,
    }
    return ElementClassifier(**{**defaults, **overrides})


def _reading_order(**overrides: Any) -> ReadingOrderResolver:
    defaults: dict[str, Any] = {"min_gutter_width": 24.0, "min_column_width": 90.0}
    return ReadingOrderResolver(**{**defaults, **overrides})


def _parser(
    classifier: PageClassifier | None = None,
    element_classifier: ElementClassifier | None = None,
    reading_order: ReadingOrderResolver | None = None,
    *,
    paragraph_gap_multiplier: float = 1.6,
    min_element_characters: int = 2,
) -> PdfPlumberParser:
    return PdfPlumberParser(
        classifier or _classifier(),
        element_classifier or _element_classifier(),
        reading_order or _reading_order(),
        paragraph_gap_multiplier=paragraph_gap_multiplier,
        min_element_characters=min_element_characters,
        min_gutter_width=24.0,
    )


async def _parse(name: str, parser: PdfPlumberParser | None = None) -> list[Any]:
    return list(
        await (parser or _parser()).parse(
            _pdf(name), document_id=_DOCUMENT_ID, scope=_SCOPE
        )
    )


def _pairs(parsed: list[Any]) -> list[tuple[Any, Any]]:
    """Page and elements together, for assertions that need to compare the two."""
    return [(item.page, item.elements) for item in parsed]


def _snapshot(parsed: list[Any]) -> list[dict[str, Any]]:
    """Everything about the parse that is stable across runs."""
    return [
        {
            "page_number": page.page_number,
            "kind": page.kind.value,
            "width": round(page.width, 2),
            "height": round(page.height, 2),
            "rotation": page.rotation,
            "elements": [
                {
                    "reading_order": element.reading_order,
                    "element_type": element.element_type.value,
                    "processing_method": element.processing_method.value,
                    "text": element.text.value,
                    "heading_path": list(element.heading_path.segments),
                    "bounding_box": (
                        None
                        if element.bounding_box is None
                        else [
                            round(element.bounding_box.x0, 1),
                            round(element.bounding_box.y0, 1),
                            round(element.bounding_box.x1, 1),
                            round(element.bounding_box.y1, 1),
                        ]
                    ),
                }
                for element in elements
            ],
        }
        for page, elements in _pairs(parsed)
    ]


# ---------------------------------------------------------------------------
# Golden file
# ---------------------------------------------------------------------------


class TestGoldenFile:
    async def test_parse_matches_the_committed_snapshot(self) -> None:
        parsed = await _parse("native_text_sample")
        expected = json.loads(_GOLDEN.read_text(encoding="utf-8"))
        assert _snapshot(parsed) == expected


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


class TestPages:
    async def test_one_page_record_per_page(self) -> None:
        parsed = await _parse("native_text_sample")
        assert [item.page.page_number for item in parsed] == [1, 2]

    async def test_pages_carry_dimensions(self) -> None:
        page = (await _parse("native_text_sample"))[0].page
        assert (page.width, page.height) == (612.0, 792.0)

    async def test_pages_are_scoped_to_the_caller(self) -> None:
        parsed = await _parse("native_text_sample")
        for page in (item.page for item in parsed):
            assert page.scope == _SCOPE
            assert page.document_id == _DOCUMENT_ID

    async def test_dense_prose_classifies_as_native_text(self) -> None:
        page = (await _parse("native_text_sample"))[0].page
        assert page.kind is PageKind.NATIVE_TEXT

    async def test_a_page_with_nothing_on_it_is_still_recorded(self) -> None:
        parsed = await _parse("empty_page_sample")
        assert len(parsed) == 1
        page, elements = parsed[0].page, parsed[0].elements
        assert page.page_number == 1
        assert list(elements) == []

    async def test_rotation_is_recorded(self) -> None:
        page = (await _parse("rotated_sample"))[0].page
        assert page.rotation == 90

    async def test_rotated_pages_report_presented_dimensions(self) -> None:
        """A quarter-turned page is wider than it is tall, and is stored that way."""
        page = (await _parse("rotated_sample"))[0].page
        assert page.width > page.height


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


class TestElements:
    async def test_a_page_of_prose_yields_a_heading_and_paragraphs(self) -> None:
        elements = (await _parse("native_text_sample"))[0].elements
        assert elements[0].element_type is ElementType.HEADING
        assert all(e.element_type is ElementType.PARAGRAPH for e in elements[1:])

    async def test_every_element_records_how_it_was_obtained(self) -> None:
        parsed = await _parse("native_text_sample")
        for elements in (item.elements for item in parsed):
            assert all(e.processing_method is ProcessingMethod.NATIVE_TEXT for e in elements)

    async def test_reading_order_starts_at_zero_and_is_contiguous_per_page(self) -> None:
        parsed = await _parse("native_text_sample")
        for elements in (item.elements for item in parsed):
            assert [e.reading_order for e in elements] == list(range(len(elements)))

    async def test_elements_are_scoped_to_the_caller(self) -> None:
        parsed = await _parse("native_text_sample")
        for elements in (item.elements for item in parsed):
            for element in elements:
                assert element.scope == _SCOPE
                assert element.document_id == _DOCUMENT_ID

    async def test_element_page_number_matches_its_page(self) -> None:
        parsed = await _parse("native_text_sample")
        for page, elements in _pairs(parsed):
            assert all(e.page_number == page.page_number for e in elements)

    async def test_a_single_line_page_yields_one_element(self) -> None:
        parsed = await _parse("single_line_sample")
        elements = parsed[0].elements
        assert len(elements) == 1
        assert elements[0].text.value == "Only one line."

    async def test_extracted_text_is_untrusted(self) -> None:
        """It came out of a file a student uploaded, so it is evidence, not instruction."""
        parsed = await _parse("single_line_sample")
        elements = parsed[0].elements
        assert "Only one line." not in str(elements[0].text)


# ---------------------------------------------------------------------------
# Paragraph grouping
# ---------------------------------------------------------------------------


class TestParagraphGrouping:
    async def test_lines_at_ordinary_leading_join_one_paragraph(self) -> None:
        elements = (await _parse("native_text_sample"))[0].elements
        body = elements[1]
        assert "chain rule" in body.text.value
        assert "tractable" in body.text.value

    async def test_a_wide_gap_starts_a_new_paragraph(self) -> None:
        elements = (await _parse("native_text_sample"))[0].elements
        assert len(elements) > 1

    async def test_a_heading_does_not_absorb_the_paragraph_below_it(self) -> None:
        """The gap under a heading is modest next to the heading and generous next to
        the body, which is why the smaller of the two lines is the reference."""
        elements = (await _parse("native_text_sample"))[0].elements
        assert elements[0].text.value == "Introduction to Backpropagation"

    async def test_a_larger_multiplier_groups_more_aggressively(self) -> None:
        """Raising the gap tolerance merges the paragraphs, but not the heading with
        them: a change of type size ends a block whatever the spacing allows."""
        loose = _parser(paragraph_gap_multiplier=100.0)
        elements = (await _parse("native_text_sample", loose))[0].elements
        assert len(elements) == 2
        assert elements[0].element_type is ElementType.HEADING
        assert elements[1].element_type is ElementType.PARAGRAPH

    async def test_short_fragments_are_discarded(self) -> None:
        strict = _parser(min_element_characters=10_000)
        elements = (await _parse("native_text_sample", strict))[0].elements
        assert list(elements) == []


# ---------------------------------------------------------------------------
# Element typing
# ---------------------------------------------------------------------------


class TestElementTyping:
    async def test_a_larger_opening_line_is_typed_as_a_heading(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        assert elements[0].element_type is ElementType.HEADING
        assert elements[0].text.value == "Results and Discussion"

    async def test_bulleted_lines_are_typed_as_a_list(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        lists = [e for e in elements if e.element_type is ElementType.LIST]
        assert len(lists) == 1

    async def test_list_items_keep_their_own_lines(self) -> None:
        """Prose wraps mid-sentence and rejoins with a space; list items do not wrap,
        and joining them that way runs them into a sentence nobody wrote."""
        elements = (await _parse("structured_sample"))[0].elements
        items = next(e for e in elements if e.element_type is ElementType.LIST)
        assert items.text.value.splitlines() == [
            "- Accuracy improved on every run",
            "- Loss decreased monotonically",
            "- Variance across runs stayed small",
        ]

    async def test_labelled_lines_are_typed_as_captions(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        captions = [e for e in elements if e.element_type is ElementType.CAPTION]
        assert len(captions) == 2
        assert captions[0].text.value.startswith("Table 1:")
        assert captions[1].text.value.startswith("Figure 1:")

    async def test_typing_is_relative_to_the_page(self) -> None:
        """Raising the ratio past what the fixture's heading achieves demotes it, which
        is only possible because the comparison is against the page rather than a fixed
        size."""
        strict = _parser(element_classifier=_element_classifier(heading_size_ratio=10.0))
        elements = (await _parse("structured_sample", strict))[0].elements
        assert elements[0].element_type is ElementType.PARAGRAPH


# ---------------------------------------------------------------------------
# Tables and figures
# ---------------------------------------------------------------------------


class TestTableAndFigureRegions:
    async def test_a_ruled_table_is_found(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        tables = [e for e in elements if e.element_type is ElementType.TABLE]
        assert len(tables) == 1

    async def test_the_table_carries_its_rows(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        table = next(e for e in elements if e.element_type is ElementType.TABLE)
        assert table.text.value.splitlines() == [
            "Run | Accuracy",
            "1 | 0.91",
            "2 | 0.94",
        ]

    async def test_the_table_carries_a_bounding_box(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        table = next(e for e in elements if e.element_type is ElementType.TABLE)
        assert table.bounding_box is not None
        assert table.bounding_box.area > 0

    async def test_table_text_is_not_also_read_as_prose(self) -> None:
        """Left in, the cells would appear twice, and the flattened copy is the one that
        mixes rows together and loses which column a number came from."""
        elements = (await _parse("structured_sample"))[0].elements
        prose = [
            e.text.value
            for e in elements
            if e.element_type in {ElementType.PARAGRAPH, ElementType.LIST}
        ]
        assert not any("0.91" in text for text in prose)

    async def test_an_embedded_image_is_found(self) -> None:
        elements = (await _parse("structured_sample"))[0].elements
        figures = [e for e in elements if e.element_type is ElementType.FIGURE]
        assert len(figures) == 1

    async def test_the_figure_carries_a_box_and_no_text(self) -> None:
        """A figure has nothing to say until something looks at it. Inventing a
        description here would put text into the document that is not in it."""
        elements = (await _parse("structured_sample"))[0].elements
        figure = next(e for e in elements if e.element_type is ElementType.FIGURE)
        assert figure.text.value == ""
        assert figure.bounding_box is not None

    async def test_elements_are_ordered_down_the_page(self) -> None:
        """Tables and figures are found by different means from text and have to be
        interleaved with it, not appended after it."""
        elements = (await _parse("structured_sample"))[0].elements
        tops = [e.bounding_box.y1 for e in elements if e.bounding_box is not None]
        assert tops == sorted(tops, reverse=True)

    async def test_a_page_without_either_yields_neither(self) -> None:
        parsed = await _parse("native_text_sample")
        for elements in (item.elements for item in parsed):
            assert not any(
                e.element_type in {ElementType.TABLE, ElementType.FIGURE}
                for e in elements
            )


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------


class TestBoundingBoxes:
    async def test_boxes_use_a_bottom_left_origin(self) -> None:
        """pdfplumber measures downwards from the top; a bounding box measures upwards
        from the bottom, so the first element on a page must sit higher, not lower."""
        elements = (await _parse("native_text_sample"))[0].elements
        first, last = elements[0].bounding_box, elements[-1].bounding_box
        assert first is not None and last is not None
        assert first.y0 > last.y1

    async def test_boxes_stay_within_the_page(self) -> None:
        parsed = await _parse("native_text_sample")
        for page, elements in _pairs(parsed):
            for element in elements:
                box = element.bounding_box
                assert box is not None
                assert 0 <= box.x0 < box.x1 <= page.width
                assert 0 <= box.y0 < box.y1 <= page.height

    async def test_a_paragraph_box_encloses_all_its_lines(self) -> None:
        elements = (await _parse("native_text_sample"))[0].elements
        multi_line = elements[1].bounding_box
        assert multi_line is not None
        # Several lines at ten-point leading are taller than any single line.
        assert multi_line.height > 20


# ---------------------------------------------------------------------------
# Columns and reading order
# ---------------------------------------------------------------------------


class TestMultiColumnReadingOrder:
    async def test_the_left_column_is_read_before_the_right(self) -> None:
        """The failure this prevents is silent: ordering by height alone interleaves the
        columns line by line, and the text is concatenated before anyone can notice."""
        elements = (await _parse("two_column_sample"))[0].elements
        text = [e.text.value for e in elements]
        left = next(i for i, t in enumerate(text) if t.startswith("Left column line 1"))
        right = next(i for i, t in enumerate(text) if t.startswith("Right column line 1"))
        assert left < right

    async def test_a_column_is_not_broken_across_its_lines(self) -> None:
        elements = (await _parse("two_column_sample"))[0].elements
        upper_left = next(
            e for e in elements if e.text.value.startswith("Left column line 1")
        )
        assert "Left column line 6" in upper_left.text.value
        assert "Right column" not in upper_left.text.value

    async def test_column_text_is_never_woven_together(self) -> None:
        elements = (await _parse("two_column_sample"))[0].elements
        for element in elements:
            text = element.text.value
            assert not ("Left column" in text and "Right column" in text)

    async def test_a_spanning_heading_is_read_before_both_columns(self) -> None:
        elements = (await _parse("two_column_sample"))[0].elements
        assert elements[0].text.value == "A Heading Across Both Columns"

    async def test_a_spanning_figure_separates_the_bands(self) -> None:
        """Everything above the figure is read before it and everything below after,
        rather than the columns running straight past it."""
        elements = (await _parse("two_column_sample"))[0].elements
        text = [e.text.value for e in elements]
        figure = next(
            i for i, e in enumerate(elements) if e.element_type is ElementType.FIGURE
        )
        upper_right = next(i for i, t in enumerate(text) if t.startswith("Right column"))
        lower_left = next(i for i, t in enumerate(text) if t.startswith("Lower left"))
        assert upper_right < figure < lower_left

    async def test_a_single_column_page_is_unaffected(self) -> None:
        """Column handling must not disturb the ordinary case, which is most pages."""
        elements = (await _parse("native_text_sample"))[0].elements
        tops = [e.bounding_box.y1 for e in elements if e.bounding_box is not None]
        assert tops == sorted(tops, reverse=True)


# ---------------------------------------------------------------------------
# Heading paths
# ---------------------------------------------------------------------------


class TestHeadingPaths:
    async def test_content_carries_the_heading_above_it(self) -> None:
        elements = (await _parse("native_text_sample"))[0].elements
        body = elements[1]
        assert body.heading_path.segments == ("Introduction to Backpropagation",)

    async def test_a_heading_carries_its_own_path(self) -> None:
        elements = (await _parse("native_text_sample"))[0].elements
        assert elements[0].heading_path.leaf == "Introduction to Backpropagation"

    async def test_a_smaller_heading_nests_beneath_a_larger_one(self) -> None:
        elements = (await _parse("section_across_pages_sample"))[0].elements
        section = elements[1]
        assert section.heading_path.segments == ("Chapter Three", "Gradient Descent")

    async def test_a_section_survives_a_page_break(self) -> None:
        """The second page opens with body text and no heading of its own. State rebuilt
        per page would show it as belonging to nothing, which is exactly where a chunk
        has the least context of its own to fall back on."""
        parsed = await _parse("section_across_pages_sample")
        second_page_elements = parsed[1].elements
        assert second_page_elements[0].heading_path.segments == (
            "Chapter Three",
            "Gradient Descent",
        )

    async def test_a_new_heading_replaces_the_previous_one(self) -> None:
        parsed = await _parse("native_text_sample")
        second = parsed[1].elements
        assert second[0].heading_path.segments == ("The Backward Pass in Detail",)

    async def test_two_headings_of_different_sizes_stay_separate(self) -> None:
        """A chapter title immediately above a section title sits at ordinary leading,
        and without a size break the two would be joined into one element."""
        elements = (await _parse("section_across_pages_sample"))[0].elements
        assert elements[0].text.value == "Chapter Three"
        assert elements[1].text.value == "Gradient Descent"


# ---------------------------------------------------------------------------
# Pages the text layer cannot serve
# ---------------------------------------------------------------------------


class TestPagesLeftForRecognition:
    async def test_scanned_pages_return_no_elements(self) -> None:
        always_scanned = _classifier(
            min_native_characters=10**9, image_coverage_threshold=0.0
        )
        parsed = await _parse("native_text_sample", _parser(always_scanned))
        for page, elements in _pairs(parsed):
            assert page.kind is PageKind.SCANNED
            assert list(elements) == []

    async def test_complex_pages_return_no_elements(self) -> None:
        always_complex = _classifier(complex_vector_drawing_threshold=0)
        parsed = await _parse("native_text_sample", _parser(always_complex))
        for page, elements in _pairs(parsed):
            assert page.kind is PageKind.COMPLEX
            assert list(elements) == []

    async def test_the_page_record_survives_even_with_no_elements(self) -> None:
        """The page is still known to exist and still known to need recognition."""
        parsed = await _parse(
            "native_text_sample",
            _parser(_classifier(min_native_characters=10**9, image_coverage_threshold=0.0)),
        )
        assert [item.page.page_number for item in parsed] == [1, 2]


# ---------------------------------------------------------------------------
# Files that cannot be read
# ---------------------------------------------------------------------------


class TestUnreadableFiles:
    async def test_a_document_with_no_pages_is_refused(self) -> None:
        with pytest.raises(UploadValidationError, match="no pages"):
            await _parse("no_pages_sample")

    async def test_arbitrary_bytes_are_refused(self) -> None:
        with pytest.raises(UploadValidationError):
            await _parser().parse(
                b"this is not a PDF", document_id=_DOCUMENT_ID, scope=_SCOPE
            )

    async def test_empty_input_is_refused(self) -> None:
        with pytest.raises(UploadValidationError):
            await _parser().parse(b"", document_id=_DOCUMENT_ID, scope=_SCOPE)

    async def test_a_truncated_pdf_is_refused_rather_than_half_read(self) -> None:
        """Half a document is worse than none: the missing half is invisible afterwards."""
        truncated = _pdf("native_text_sample")[:400]
        with pytest.raises(UploadValidationError):
            await _parser().parse(truncated, document_id=_DOCUMENT_ID, scope=_SCOPE)


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestParsingDoesNotBlockTheLoop:
    async def test_other_tasks_run_while_a_parse_is_in_flight(self) -> None:
        """The worker holds its job lease with a heartbeat on this same loop. A parse
        that blocked it would let the lease expire while the work it covers is running."""
        ticks = 0

        async def _ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0)
                ticks += 1

        ticker = asyncio.create_task(_ticker())
        try:
            await _parse("native_text_sample")
        finally:
            ticker.cancel()

        assert ticks > 0


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class TestTables:
    async def test_a_ruled_table_is_read_into_a_record(self) -> None:
        tables = (await _parse("structured_sample"))[0].tables
        assert len(tables) == 1

    async def test_its_columns_are_named_from_the_header_row(self) -> None:
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.headers == ("Run", "Accuracy")

    async def test_its_data_rows_survive_intact(self) -> None:
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.rows == (("1", "0.91"), ("2", "0.94"))

    async def test_a_column_can_be_read_back_by_name(self) -> None:
        # The whole point of the record: the joined element text cannot answer this.
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.column("Accuracy") == ("0.91", "0.94")

    async def test_it_names_the_element_it_was_read_from(self) -> None:
        parsed = (await _parse("structured_sample"))[0]
        table = parsed.tables[0]
        element_ids = {e.id for e in parsed.elements if e.element_type is ElementType.TABLE}
        assert table.source_element_id in element_ids

    async def test_it_is_scoped_to_the_caller(self) -> None:
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.scope == _SCOPE
        assert table.document_id == _DOCUMENT_ID

    async def test_it_carries_the_page_it_sits_on(self) -> None:
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.page_number == 1

    async def test_it_carries_a_region_that_can_be_highlighted(self) -> None:
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.bounding_box.x1 > table.bounding_box.x0
        assert table.bounding_box.y1 > table.bounding_box.y0

    async def test_the_caption_below_it_is_attached(self) -> None:
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.caption is not None
        assert "Accuracy by run" in table.caption.value

    async def test_a_figures_caption_is_not_claimed_by_the_table(self) -> None:
        # The same page carries "Figure 1: ...". Attaching it here would put a
        # description of a loss curve onto a table of accuracies.
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.caption is not None
        assert "Loss curve" not in table.caption.value

    async def test_a_page_with_no_table_produces_none(self) -> None:
        parsed = await _parse("native_text_sample")
        assert all(item.tables == [] for item in parsed)

    async def test_a_page_left_for_recognition_produces_no_tables(self) -> None:
        always_scanned = _classifier(
            min_native_characters=10**9, image_coverage_threshold=0.0
        )
        parsed = await _parse("structured_sample", _parser(always_scanned))
        assert all(list(item.tables) == [] for item in parsed)

    async def test_the_element_still_carries_the_joined_reading(self) -> None:
        # The record and the element describe the same region for different purposes;
        # adding one must not empty the other, which is what reading order matches on.
        parsed = (await _parse("structured_sample"))[0]
        table_elements = [
            e for e in parsed.elements if e.element_type is ElementType.TABLE
        ]
        assert table_elements
        assert "0.91" in table_elements[0].text.value


class TestTableNumbers:
    async def test_the_number_the_document_printed_is_extracted(self) -> None:
        # The fixture captions its table "Table 1: Accuracy by run."
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.number == "1"

    async def test_the_caption_is_kept_whole_alongside_the_number(self) -> None:
        # The number is extracted from the caption, not removed from it — a caption
        # should still read the way the document wrote it.
        table = (await _parse("structured_sample"))[0].tables[0]
        assert table.caption is not None
        assert "Table 1" in table.caption.value

    async def test_a_table_with_no_caption_has_no_number(self) -> None:
        parsed = await _parse("two_column_sample")
        for item in parsed:
            for table in item.tables:
                if table.caption is None:
                    assert table.number is None


class TestFigureRecords:
    async def test_a_detected_image_produces_a_figure_record(self) -> None:
        item = (await _parse("structured_sample"))[0]
        assert len(item.figures) == 1

    async def test_the_figure_record_carries_a_bounding_box(self) -> None:
        fig = (await _parse("structured_sample"))[0].figures[0]
        assert fig.bounding_box.x1 > fig.bounding_box.x0
        assert fig.bounding_box.y1 > fig.bounding_box.y0

    async def test_the_figure_record_has_figure_kind(self) -> None:
        fig = (await _parse("structured_sample"))[0].figures[0]
        assert fig.kind is ElementType.FIGURE

    async def test_the_figure_caption_is_attached(self) -> None:
        # The structured_sample fixture has "Figure 1: Loss curve for run 3."
        fig = (await _parse("structured_sample"))[0].figures[0]
        assert fig.caption is not None
        assert "Loss curve" in fig.caption.value

    async def test_the_figure_number_is_extracted(self) -> None:
        fig = (await _parse("structured_sample"))[0].figures[0]
        assert fig.number == "1"

    async def test_the_figure_caption_is_not_claimed_by_the_nearby_table(self) -> None:
        # The table lives on the same page and must take "Table 1:", not "Figure 1:".
        fig = (await _parse("structured_sample"))[0].figures[0]
        assert fig.caption is not None
        assert "Accuracy by run" not in fig.caption.value

    async def test_a_page_left_for_recognition_produces_no_figure_records(self) -> None:
        always_scanned = _classifier(
            min_native_characters=10**9, image_coverage_threshold=0.0
        )
        parsed = await _parse("structured_sample", _parser(always_scanned))
        assert all(list(item.figures) == [] for item in parsed)

    async def test_a_page_with_no_images_produces_no_figure_records(self) -> None:
        parsed = await _parse("native_text_sample")
        assert all(item.figures == [] for item in parsed)


class TestRunningHeaderSuppression:
    async def test_the_repeated_heading_is_excluded_from_elements(self) -> None:
        # "Machine Learning" appears on all 4 pages and must be dropped entirely —
        # not reclassified to PARAGRAPH and left in the element list.
        parsed = await _parse("running_header_sample")
        all_texts = {e.text.value.strip() for item in parsed for e in item.elements}
        assert "Machine Learning" not in all_texts

    async def test_real_chapter_headings_are_kept(self) -> None:
        parsed = await _parse("running_header_sample")
        headings = [
            e
            for item in parsed
            for e in item.elements
            if e.element_type is ElementType.HEADING
        ]
        heading_texts = {h.text.value for h in headings}
        assert "Chapter One" in heading_texts
        assert "Chapter Two" in heading_texts

    async def test_content_is_under_the_real_chapter_not_the_running_header(self) -> None:
        # Body text on page 1 should be under "Chapter One", not under "Machine Learning".
        parsed = await _parse("running_header_sample")
        page_one_paragraphs = [
            e
            for e in parsed[0].elements
            if e.element_type is ElementType.PARAGRAPH
            and "Gradient descent" in e.text.value
        ]
        assert page_one_paragraphs
        path_segments = list(page_one_paragraphs[0].heading_path.segments)
        assert "Machine Learning" not in path_segments
        assert "Chapter One" in path_segments

    async def test_page_with_no_chapter_heading_keeps_the_previous_chapter_in_path(self) -> None:
        # Page 2 has no chapter heading; content there should still be under "Chapter One"
        # from page 1, because a section carries over until a new one opens.
        parsed = await _parse("running_header_sample")
        page_two_paragraphs = [
            e
            for e in parsed[1].elements
            if e.element_type is ElementType.PARAGRAPH
            and "Gradient descent" in e.text.value
        ]
        assert page_two_paragraphs
        path_segments = list(page_two_paragraphs[0].heading_path.segments)
        assert "Chapter One" in path_segments

    async def test_a_heading_on_few_pages_is_not_suppressed(self) -> None:
        # "Chapter One" and "Chapter Two" each appear on exactly one page out of four
        # and must survive the threshold.
        parsed = await _parse("running_header_sample")
        chapter_elements = [
            e
            for item in parsed
            for e in item.elements
            if e.text.value in {"Chapter One", "Chapter Two"}
        ]
        assert all(e.element_type is ElementType.HEADING for e in chapter_elements)


class TestBodySizeRunningHeaderSuppression:
    """Running headers set at body size are classified as PARAGRAPH before the suppressor
    runs, so the HEADING-only check misses them. The suppressor must scan the PARAGRAPH
    population in the top margin as well, and drop those elements entirely."""

    async def test_body_size_running_header_is_excluded_from_elements(self) -> None:
        # "Machine Learning" at 10pt (body size) appears in the top margin on all 4
        # pages. It must be absent from the element list, not reclassified to PARAGRAPH.
        parsed = await _parse("body_size_running_header_sample")
        all_texts = {e.text.value.strip() for item in parsed for e in item.elements}
        assert "Machine Learning" not in all_texts

    async def test_chapter_headings_are_kept(self) -> None:
        parsed = await _parse("body_size_running_header_sample")
        heading_texts = {
            e.text.value
            for item in parsed
            for e in item.elements
            if e.element_type is ElementType.HEADING
        }
        assert "Chapter One" in heading_texts
        assert "Chapter Two" in heading_texts

    async def test_body_text_is_under_the_chapter_heading(self) -> None:
        # Body paragraphs on page 1 should be under "Chapter One", not under nothing
        # and not under "Machine Learning".
        parsed = await _parse("body_size_running_header_sample")
        page_one_paragraphs = [
            e
            for e in parsed[0].elements
            if e.element_type is ElementType.PARAGRAPH
            and "Gradient descent" in e.text.value
        ]
        assert page_one_paragraphs
        path_segments = list(page_one_paragraphs[0].heading_path.segments)
        assert "Machine Learning" not in path_segments
        assert "Chapter One" in path_segments
