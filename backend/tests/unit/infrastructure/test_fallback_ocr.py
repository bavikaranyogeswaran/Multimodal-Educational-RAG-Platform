"""Unit tests for the fallback OCR adapter and Tesseract adapter.

FallbackOcrAdapter tests:
  - Primary is used when it returns acceptable results.
  - VL secondary is triggered when the primary result is empty.
  - VL secondary is triggered when average confidence is below the threshold.
  - VL secondary is skipped when `secondary=None` (VL disabled).
  - When all elements have no confidence recorded, the primary result is kept.

TesseractAdapter tests:
  - Elements are built with the correct scope and confidence.
  - Words with conf=-1 (non-word rows) are skipped.
  - Blank text words are skipped.
  - A missing pytesseract / PIL import returns an empty list gracefully.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.documents.entities import DocumentPage
from app.domain.enums import PageKind
from app.domain.scope import ScopeContext
from app.infrastructure.ocr.fallback import FallbackOcrAdapter, _needs_fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _page(scope: ScopeContext) -> DocumentPage:
    return DocumentPage(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=uuid.uuid4(),
        page_number=1,
        kind=PageKind.SCANNED,
        width=595.0,
        height=841.0,
    )


def _element(scope: ScopeContext, *, confidence: float | None = 0.9) -> MagicMock:
    el = MagicMock()
    el.confidence = confidence
    el.user_id = scope.user_id
    el.knowledge_base_id = scope.knowledge_base_id
    return el


# ---------------------------------------------------------------------------
# _needs_fallback unit tests
# ---------------------------------------------------------------------------


def test_needs_fallback_true_for_empty_result() -> None:
    assert _needs_fallback([], confidence_threshold=0.65) is True


def test_needs_fallback_false_when_avg_confidence_above_threshold() -> None:
    scope = _scope()
    elements = [_element(scope, confidence=0.80), _element(scope, confidence=0.90)]
    assert _needs_fallback(elements, confidence_threshold=0.65) is False


def test_needs_fallback_true_when_avg_confidence_below_threshold() -> None:
    scope = _scope()
    elements = [_element(scope, confidence=0.40), _element(scope, confidence=0.50)]
    assert _needs_fallback(elements, confidence_threshold=0.65) is True


def test_needs_fallback_false_when_no_confidence_recorded() -> None:
    scope = _scope()
    elements = [_element(scope, confidence=None), _element(scope, confidence=None)]
    assert _needs_fallback(elements, confidence_threshold=0.65) is False


def test_needs_fallback_uses_only_elements_with_confidence() -> None:
    scope = _scope()
    # One element with high confidence, one with None — avg of [0.9] = 0.9 > 0.65
    elements = [_element(scope, confidence=0.90), _element(scope, confidence=None)]
    assert _needs_fallback(elements, confidence_threshold=0.65) is False


# ---------------------------------------------------------------------------
# FallbackOcrAdapter dispatch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_primary_result_returned_when_acceptable() -> None:
    scope = _scope()
    page = _page(scope)
    good_element = _element(scope, confidence=0.90)

    primary = AsyncMock()
    primary.extract_text = AsyncMock(return_value=[good_element])
    secondary = AsyncMock()

    adapter = FallbackOcrAdapter(
        primary=primary, secondary=secondary, confidence_threshold=0.65
    )
    result = await adapter.extract_text(b"img", page=page)

    assert result == [good_element]
    secondary.extract_text.assert_not_called()


@pytest.mark.asyncio
async def test_secondary_triggered_when_primary_returns_empty() -> None:
    scope = _scope()
    page = _page(scope)
    vl_element = _element(scope, confidence=0.88)

    primary = AsyncMock()
    primary.extract_text = AsyncMock(return_value=[])
    secondary = AsyncMock()
    secondary.extract_text = AsyncMock(return_value=[vl_element])

    adapter = FallbackOcrAdapter(
        primary=primary, secondary=secondary, confidence_threshold=0.65
    )
    result = await adapter.extract_text(b"img", page=page)

    assert result == [vl_element]
    secondary.extract_text.assert_called_once_with(b"img", page=page)


@pytest.mark.asyncio
async def test_secondary_triggered_when_primary_confidence_low() -> None:
    scope = _scope()
    page = _page(scope)
    poor_element = _element(scope, confidence=0.30)
    vl_element = _element(scope, confidence=0.85)

    primary = AsyncMock()
    primary.extract_text = AsyncMock(return_value=[poor_element])
    secondary = AsyncMock()
    secondary.extract_text = AsyncMock(return_value=[vl_element])

    adapter = FallbackOcrAdapter(
        primary=primary, secondary=secondary, confidence_threshold=0.65
    )
    result = await adapter.extract_text(b"img", page=page)

    assert result == [vl_element]


@pytest.mark.asyncio
async def test_secondary_none_returns_primary_even_when_poor() -> None:
    scope = _scope()
    page = _page(scope)
    poor_element = _element(scope, confidence=0.20)

    primary = AsyncMock()
    primary.extract_text = AsyncMock(return_value=[poor_element])

    adapter = FallbackOcrAdapter(
        primary=primary, secondary=None, confidence_threshold=0.65
    )
    result = await adapter.extract_text(b"img", page=page)

    assert result == [poor_element]


# ---------------------------------------------------------------------------
# TesseractAdapter tests
# ---------------------------------------------------------------------------


def _make_tesseract_data(
    texts: list[str],
    confs: list[int],
    lefts: list[int],
    tops: list[int],
    widths: list[int],
    heights: list[int],
) -> dict:
    return {
        "text": texts,
        "conf": confs,
        "left": lefts,
        "top": tops,
        "width": widths,
        "height": heights,
    }


def _make_tess_mocks(tess_data: dict) -> tuple[MagicMock, MagicMock, dict]:
    """Return (mock_tess, mock_pil, sys_modules_patch) for patching inside _extract_blocking."""
    mock_img = MagicMock()
    mock_image_module = MagicMock()
    mock_image_module.open.return_value = mock_img
    mock_pil = MagicMock()
    mock_pil.Image = mock_image_module
    mock_tess = MagicMock()
    mock_tess.image_to_data.return_value = tess_data
    mock_tess.Output.DICT = "dict"
    modules = {
        "pytesseract": mock_tess,
        "PIL": mock_pil,
        "PIL.Image": mock_image_module,
    }
    return mock_tess, mock_pil, modules


@pytest.mark.asyncio
async def test_tesseract_builds_elements_with_correct_scope() -> None:
    from app.infrastructure.ocr.tesseract import TesseractAdapter

    scope = _scope()
    page = _page(scope)
    adapter = TesseractAdapter(lang="eng", dpi=200)

    tess_data = _make_tesseract_data(
        texts=["Hello"],
        confs=[90],
        lefts=[10],
        tops=[20],
        widths=[100],
        heights=[30],
    )
    _, _, modules = _make_tess_mocks(tess_data)

    with patch.dict("sys.modules", modules):
        elements = await adapter.extract_text(b"fake-png", page=page)

    assert len(elements) == 1
    assert elements[0].user_id == scope.user_id
    assert elements[0].knowledge_base_id == scope.knowledge_base_id
    assert elements[0].text.value == "Hello"
    assert abs(elements[0].confidence - 0.90) < 1e-6


@pytest.mark.asyncio
async def test_tesseract_skips_negative_confidence_rows() -> None:
    from app.infrastructure.ocr.tesseract import TesseractAdapter

    scope = _scope()
    page = _page(scope)
    adapter = TesseractAdapter(lang="eng", dpi=200)

    tess_data = _make_tesseract_data(
        texts=["block-level", "Real word"],
        confs=[-1, 85],
        lefts=[0, 10],
        tops=[0, 20],
        widths=[200, 100],
        heights=[50, 30],
    )
    _, _, modules = _make_tess_mocks(tess_data)

    with patch.dict("sys.modules", modules):
        elements = await adapter.extract_text(b"fake-png", page=page)

    assert len(elements) == 1
    assert elements[0].text.value == "Real word"


@pytest.mark.asyncio
async def test_tesseract_skips_blank_text() -> None:
    from app.infrastructure.ocr.tesseract import TesseractAdapter

    scope = _scope()
    page = _page(scope)
    adapter = TesseractAdapter(lang="eng", dpi=200)

    tess_data = _make_tesseract_data(
        texts=["", "   ", "Word"],
        confs=[80, 80, 80],
        lefts=[0, 0, 10],
        tops=[0, 10, 20],
        widths=[50, 50, 80],
        heights=[20, 20, 25],
    )
    _, _, modules = _make_tess_mocks(tess_data)

    with patch.dict("sys.modules", modules):
        elements = await adapter.extract_text(b"fake-png", page=page)

    assert len(elements) == 1
    assert elements[0].text.value == "Word"


@pytest.mark.asyncio
async def test_tesseract_returns_empty_when_pytesseract_unavailable() -> None:
    from app.infrastructure.ocr.tesseract import TesseractAdapter

    scope = _scope()
    page = _page(scope)
    adapter = TesseractAdapter(lang="eng", dpi=200)

    import sys

    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k in {"pytesseract", "PIL"}}
    try:
        with patch.dict("sys.modules", {"pytesseract": None, "PIL": None}):
            elements = await adapter.extract_text(b"fake-png", page=page)
    finally:
        sys.modules.update(saved)

    assert elements == []
