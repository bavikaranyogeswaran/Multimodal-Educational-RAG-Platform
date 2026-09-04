"""Unit tests for the PaddleOCR adapter.

PaddleOCR is a heavy optional dependency — the test suite does not install it.
Every test patches `_get_engine` so no model is loaded, making these tests
runnable in any environment and fast regardless of hardware.

Three properties carry the weight:

  1. Coordinate conversion — pixels at the render DPI are mapped correctly to
     PDF user-space points with the y-axis flipped.

  2. Element construction — scope, page number, processing method, and
     confidence are taken from the page object and the engine result.

  3. Filtering — blank text and degenerate bounding boxes are silently dropped;
     low-confidence results are kept with their confidence recorded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.domain.documents.entities import DocumentPage
from app.domain.enums import PageKind, ProcessingMethod
from app.infrastructure.ocr.paddle_ocr import PaddleOcrAdapter, _to_bbox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DPI = 200
_PAGE_HEIGHT_PTS = 841.0  # A4 in points


def _page(
    *,
    width: float = 595.0,
    height: float = _PAGE_HEIGHT_PTS,
    page_number: int = 1,
) -> DocumentPage:
    return DocumentPage(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page_number=page_number,
        kind=PageKind.SCANNED,
        width=width,
        height=height,
    )


def _adapter() -> PaddleOcrAdapter:
    return PaddleOcrAdapter(lang="en", dpi=_DPI)


def _engine_result(
    texts: list[str],
    scores: list[float],
    polys: list[list[list[float]]],
) -> list[dict]:
    return [{"rec_texts": texts, "rec_scores": scores, "rec_polys": polys}]


# ---------------------------------------------------------------------------
# _to_bbox — coordinate conversion
# ---------------------------------------------------------------------------


def test_to_bbox_converts_pixel_rectangle_to_pdf_points() -> None:
    # A box 100×50 px at (10, 20) in the rendered image, 200 DPI, A4 height.
    # scale = 72/200 = 0.36
    # x0 = 10 * 0.36 = 3.6,  x1 = 110 * 0.36 = 39.6
    # y_top_pts = 20 * 0.36 = 7.2,  y_bottom_pts = 70 * 0.36 = 25.2
    # y0 = 841 - 25.2 = 815.8,  y1 = 841 - 7.2 = 833.8
    poly = [[10, 20], [110, 20], [110, 70], [10, 70]]
    bbox = _to_bbox(poly, page_height=_PAGE_HEIGHT_PTS, dpi=_DPI)

    assert bbox is not None
    assert abs(bbox.x0 - 3.6) < 0.01
    assert abs(bbox.x1 - 39.6) < 0.01
    assert abs(bbox.y0 - 815.8) < 0.1
    assert abs(bbox.y1 - 833.8) < 0.1


def test_to_bbox_returns_none_for_empty_polygon() -> None:
    assert _to_bbox([], page_height=_PAGE_HEIGHT_PTS, dpi=_DPI) is None


def test_to_bbox_returns_none_for_single_point() -> None:
    assert _to_bbox([[50, 50]], page_height=_PAGE_HEIGHT_PTS, dpi=_DPI) is None


def test_to_bbox_returns_none_for_zero_width_box() -> None:
    # Same x coordinate — width would be zero, BoundingBox would refuse it.
    poly = [[50, 10], [50, 60]]
    assert _to_bbox(poly, page_height=_PAGE_HEIGHT_PTS, dpi=_DPI) is None


def test_to_bbox_handles_tilted_polygon() -> None:
    # A parallelogram — the axis-aligned bounding box should be taken.
    poly = [[20, 10], [80, 5], [90, 40], [30, 45]]
    bbox = _to_bbox(poly, page_height=_PAGE_HEIGHT_PTS, dpi=_DPI)

    assert bbox is not None
    scale = 72.0 / _DPI
    assert abs(bbox.x0 - 20 * scale) < 0.01
    assert abs(bbox.x1 - 90 * scale) < 0.01


def test_to_bbox_y_axis_flipped_correctly() -> None:
    # A box at the very top of the image (small y in pixel space) should map to
    # a large y0/y1 in PDF space (close to page_height).
    poly = [[0, 0], [100, 0], [100, 10], [0, 10]]
    bbox = _to_bbox(poly, page_height=_PAGE_HEIGHT_PTS, dpi=_DPI)

    assert bbox is not None
    # y_top_pts = 0, y_bottom_pts = 10*0.36 = 3.6
    # y0 = 841 - 3.6 = 837.4,  y1 = 841 - 0 = 841.0
    assert bbox.y0 > bbox.y1 - 5  # box is near the top of the PDF page
    assert bbox.y1 <= _PAGE_HEIGHT_PTS + 0.01


# ---------------------------------------------------------------------------
# extract_text — element construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_one_element_per_text_result() -> None:
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [200, 0], [200, 30], [0, 30]]
    result = _engine_result(["Hello world"], [0.95], [poly])

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert len(elements) == 1
    assert elements[0].text.value == "Hello world"


@pytest.mark.asyncio
async def test_element_inherits_scope_from_page() -> None:
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [200, 0], [200, 30], [0, 30]]
    result = _engine_result(["Text"], [0.9], [poly])

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    el = elements[0]
    assert el.user_id == page.user_id
    assert el.knowledge_base_id == page.knowledge_base_id
    assert el.document_id == page.document_id
    assert el.page_number == page.page_number


@pytest.mark.asyncio
async def test_processing_method_is_ocr() -> None:
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [200, 0], [200, 30], [0, 30]]
    result = _engine_result(["Text"], [0.9], [poly])

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert elements[0].processing_method is ProcessingMethod.OCR


@pytest.mark.asyncio
async def test_confidence_is_recorded_from_engine() -> None:
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [200, 0], [200, 30], [0, 30]]
    result = _engine_result(["Text"], [0.78], [poly])

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert abs(elements[0].confidence - 0.78) < 1e-6


@pytest.mark.asyncio
async def test_reading_order_assigned_sequentially() -> None:
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [100, 0], [100, 20], [0, 20]]
    result = _engine_result(
        ["First", "Second", "Third"],
        [0.9, 0.85, 0.8],
        [poly, poly, poly],
    )

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert [el.reading_order for el in elements] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blank_text_elements_are_dropped() -> None:
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [100, 0], [100, 20], [0, 20]]
    result = _engine_result(["", "   ", "Real text"], [0.9, 0.9, 0.9], [poly, poly, poly])

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert len(elements) == 1
    assert elements[0].text.value == "Real text"


@pytest.mark.asyncio
async def test_degenerate_bounding_box_is_dropped() -> None:
    page = _page()
    adapter = _adapter()
    # A polygon where all x-coordinates are the same — zero width after conversion.
    zero_width_poly = [[50.0, 0.0], [50.0, 30.0]]
    good_poly = [[0, 0], [100, 0], [100, 20], [0, 20]]
    result = _engine_result(
        ["Bad box", "Good box"],
        [0.9, 0.9],
        [zero_width_poly, good_poly],
    )

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert len(elements) == 1
    assert elements[0].text.value == "Good box"


@pytest.mark.asyncio
async def test_low_confidence_elements_are_kept() -> None:
    # The domain entity records confidence but does not discard results — the
    # use-case or downstream code decides what to do with low-confidence text.
    page = _page()
    adapter = _adapter()
    poly = [[0, 0], [200, 0], [200, 30], [0, 30]]
    result = _engine_result(["Blurry text"], [0.30], [poly])

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert len(elements) == 1
    assert elements[0].is_low_confidence


@pytest.mark.asyncio
async def test_engine_error_returns_empty_list() -> None:
    page = _page()
    adapter = _adapter()

    broken_engine = MagicMock()
    broken_engine.predict.side_effect = RuntimeError("model crash")

    with patch.object(adapter, "_get_engine", return_value=broken_engine):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert elements == []


@pytest.mark.asyncio
async def test_empty_engine_result_returns_empty_list() -> None:
    page = _page()
    adapter = _adapter()

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: [])):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert elements == []


@pytest.mark.asyncio
async def test_falls_back_to_rec_boxes_when_rec_polys_absent() -> None:
    page = _page()
    adapter = _adapter()
    box = [[0, 0], [100, 0], [100, 20], [0, 20]]
    # Engine returns rec_boxes instead of rec_polys (older API shape).
    result = [{"rec_texts": ["Text"], "rec_scores": [0.9], "rec_boxes": [box]}]

    with patch.object(adapter, "_get_engine", return_value=MagicMock(predict=lambda _: result)):
        elements = await adapter.extract_text(b"fake-image", page=page)

    assert len(elements) == 1
