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

from app.domain.documents.page_classifier import PageClassifier
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


def _parser(classifier: PageClassifier | None = None) -> PdfPlumberParser:
    return PdfPlumberParser(
        classifier or _classifier(),
        paragraph_gap_multiplier=1.6,
        min_element_characters=2,
    )


async def _parse(name: str, parser: PdfPlumberParser | None = None) -> list[Any]:
    return list(
        await (parser or _parser()).parse(
            _pdf(name), document_id=_DOCUMENT_ID, scope=_SCOPE
        )
    )


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
        for page, elements in parsed
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
        assert [page.page_number for page, _ in parsed] == [1, 2]

    async def test_pages_carry_dimensions(self) -> None:
        (page, _), *_ = await _parse("native_text_sample")
        assert (page.width, page.height) == (612.0, 792.0)

    async def test_pages_are_scoped_to_the_caller(self) -> None:
        parsed = await _parse("native_text_sample")
        for page, _ in parsed:
            assert page.scope == _SCOPE
            assert page.document_id == _DOCUMENT_ID

    async def test_dense_prose_classifies_as_native_text(self) -> None:
        (page, _), *_ = await _parse("native_text_sample")
        assert page.kind is PageKind.NATIVE_TEXT

    async def test_a_page_with_nothing_on_it_is_still_recorded(self) -> None:
        parsed = await _parse("empty_page_sample")
        assert len(parsed) == 1
        page, elements = parsed[0]
        assert page.page_number == 1
        assert list(elements) == []

    async def test_rotation_is_recorded(self) -> None:
        (page, _), *_ = await _parse("rotated_sample")
        assert page.rotation == 90

    async def test_rotated_pages_report_presented_dimensions(self) -> None:
        """A quarter-turned page is wider than it is tall, and is stored that way."""
        (page, _), *_ = await _parse("rotated_sample")
        assert page.width > page.height


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


class TestElements:
    async def test_every_element_is_a_paragraph_for_now(self) -> None:
        """Finer typing is a later step; claiming it here would be claiming more than
        has been established."""
        parsed = await _parse("native_text_sample")
        for _, elements in parsed:
            assert all(e.element_type is ElementType.PARAGRAPH for e in elements)

    async def test_every_element_records_how_it_was_obtained(self) -> None:
        parsed = await _parse("native_text_sample")
        for _, elements in parsed:
            assert all(e.processing_method is ProcessingMethod.NATIVE_TEXT for e in elements)

    async def test_reading_order_starts_at_zero_and_is_contiguous_per_page(self) -> None:
        parsed = await _parse("native_text_sample")
        for _, elements in parsed:
            assert [e.reading_order for e in elements] == list(range(len(elements)))

    async def test_elements_are_scoped_to_the_caller(self) -> None:
        parsed = await _parse("native_text_sample")
        for _, elements in parsed:
            for element in elements:
                assert element.scope == _SCOPE
                assert element.document_id == _DOCUMENT_ID

    async def test_element_page_number_matches_its_page(self) -> None:
        parsed = await _parse("native_text_sample")
        for page, elements in parsed:
            assert all(e.page_number == page.page_number for e in elements)

    async def test_a_single_line_page_yields_one_element(self) -> None:
        parsed = await _parse("single_line_sample")
        _, elements = parsed[0]
        assert len(elements) == 1
        assert elements[0].text.value == "Only one line."

    async def test_extracted_text_is_untrusted(self) -> None:
        """It came out of a file a student uploaded, so it is evidence, not instruction."""
        parsed = await _parse("single_line_sample")
        _, elements = parsed[0]
        assert "Only one line." not in str(elements[0].text)


# ---------------------------------------------------------------------------
# Paragraph grouping
# ---------------------------------------------------------------------------


class TestParagraphGrouping:
    async def test_lines_at_ordinary_leading_join_one_paragraph(self) -> None:
        (_, elements), *_ = await _parse("native_text_sample")
        body = elements[1]
        assert "chain rule" in body.text.value
        assert "tractable" in body.text.value

    async def test_a_wide_gap_starts_a_new_paragraph(self) -> None:
        (_, elements), *_ = await _parse("native_text_sample")
        assert len(elements) > 1

    async def test_a_heading_does_not_absorb_the_paragraph_below_it(self) -> None:
        """The gap under a heading is modest next to the heading and generous next to
        the body, which is why the smaller of the two lines is the reference."""
        (_, elements), *_ = await _parse("native_text_sample")
        assert elements[0].text.value == "Introduction to Backpropagation"

    async def test_a_larger_multiplier_groups_more_aggressively(self) -> None:
        loose = PdfPlumberParser(
            _classifier(), paragraph_gap_multiplier=100.0, min_element_characters=2
        )
        (_, elements), *_ = await _parse("native_text_sample", loose)
        assert len(elements) == 1

    async def test_short_fragments_are_discarded(self) -> None:
        strict = PdfPlumberParser(
            _classifier(), paragraph_gap_multiplier=1.6, min_element_characters=10_000
        )
        (_, elements), *_ = await _parse("native_text_sample", strict)
        assert list(elements) == []


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------


class TestBoundingBoxes:
    async def test_boxes_use_a_bottom_left_origin(self) -> None:
        """pdfplumber measures downwards from the top; a bounding box measures upwards
        from the bottom, so the first element on a page must sit higher, not lower."""
        (_, elements), *_ = await _parse("native_text_sample")
        first, last = elements[0].bounding_box, elements[-1].bounding_box
        assert first is not None and last is not None
        assert first.y0 > last.y1

    async def test_boxes_stay_within_the_page(self) -> None:
        parsed = await _parse("native_text_sample")
        for page, elements in parsed:
            for element in elements:
                box = element.bounding_box
                assert box is not None
                assert 0 <= box.x0 < box.x1 <= page.width
                assert 0 <= box.y0 < box.y1 <= page.height

    async def test_a_paragraph_box_encloses_all_its_lines(self) -> None:
        (_, elements), *_ = await _parse("native_text_sample")
        multi_line = elements[1].bounding_box
        assert multi_line is not None
        # Several lines at ten-point leading are taller than any single line.
        assert multi_line.height > 20


# ---------------------------------------------------------------------------
# Pages the text layer cannot serve
# ---------------------------------------------------------------------------


class TestPagesLeftForRecognition:
    async def test_scanned_pages_return_no_elements(self) -> None:
        always_scanned = _classifier(
            min_native_characters=10**9, image_coverage_threshold=0.0
        )
        parsed = await _parse("native_text_sample", _parser(always_scanned))
        for page, elements in parsed:
            assert page.kind is PageKind.SCANNED
            assert list(elements) == []

    async def test_complex_pages_return_no_elements(self) -> None:
        always_complex = _classifier(complex_vector_drawing_threshold=0)
        parsed = await _parse("native_text_sample", _parser(always_complex))
        for page, elements in parsed:
            assert page.kind is PageKind.COMPLEX
            assert list(elements) == []

    async def test_the_page_record_survives_even_with_no_elements(self) -> None:
        """The page is still known to exist and still known to need recognition."""
        parsed = await _parse(
            "native_text_sample",
            _parser(_classifier(min_native_characters=10**9, image_coverage_threshold=0.0)),
        )
        assert [page.page_number for page, _ in parsed] == [1, 2]


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
