"""Tesseract emergency fallback adapter.

Used only when PaddleOCR is entirely unavailable — typically in a CI environment
or a machine where the Paddle wheels did not install. It is never chosen over
PaddleOCR when PaddleOCR can be imported, and it is never selected as the VL
fallback (that role belongs to PaddleOCR with VL preprocessing enabled).

Tesseract returns confidence on a 0–100 integer scale. The adapter normalises
this to the 0.0–1.0 float that the domain expects.

Coordinate conversion reuses `_to_bbox` from the Paddle adapter: Tesseract also
works in pixel space with the origin at the top-left, so the same scale+flip
logic applies.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog

from app.domain.documents.entities import DocumentElement, DocumentPage
from app.domain.enums import ElementType, ProcessingMethod
from app.domain.values import UntrustedText
from app.infrastructure.ocr.paddle_ocr import _to_bbox

_log = structlog.get_logger(__name__)


class TesseractAdapter:
    """OcrPort backed by pytesseract (Tesseract 4/5).

    pytesseract and Pillow must be installed, and the Tesseract binary must be
    on the system PATH (or configured via pytesseract.pytesseract.tesseract_cmd).
    A missing binary raises an ImportError-equivalent at the first call, which
    the composition root catches when wiring falls back to _Unimplemented.
    """

    def __init__(self, *, lang: str, dpi: int) -> None:
        self._lang = lang
        self._dpi = dpi

    async def extract_text(
        self, image: bytes, *, page: DocumentPage
    ) -> Sequence[DocumentElement]:
        elements = await asyncio.to_thread(self._extract_blocking, image, page)
        _log.info(
            "tesseract_page_done",
            document_id=str(page.document_id),
            page_number=page.page_number,
            elements=len(elements),
        )
        return elements

    def _extract_blocking(
        self, image: bytes, page: DocumentPage
    ) -> list[DocumentElement]:
        try:
            import pytesseract  # type: ignore[import-untyped]
            from PIL import Image  # type: ignore[import-untyped]
        except ImportError:
            _log.error("tesseract_not_available")
            return []

        try:
            img = Image.open(io.BytesIO(image))
            data = pytesseract.image_to_data(
                img,
                lang=self._lang,
                output_type=pytesseract.Output.DICT,
            )
        except Exception:
            _log.exception(
                "tesseract_engine_error",
                document_id=str(page.document_id),
                page_number=page.page_number,
            )
            return []

        elements: list[DocumentElement] = []
        reading_order = 0
        now = datetime.now(UTC)

        for i, text in enumerate(data["text"]):
            text = str(text).strip()
            if not text:
                continue

            conf = int(data["conf"][i])
            if conf < 0:
                continue

            left = int(data["left"][i])
            top = int(data["top"][i])
            width = int(data["width"][i])
            height = int(data["height"][i])

            polygon = [
                [left, top],
                [left + width, top],
                [left + width, top + height],
                [left, top + height],
            ]
            bbox = _to_bbox(polygon, page_height=page.height, dpi=self._dpi)
            if bbox is None:
                continue

            elements.append(
                DocumentElement(
                    id=uuid.uuid4(),
                    user_id=page.user_id,
                    knowledge_base_id=page.knowledge_base_id,
                    document_id=page.document_id,
                    page_number=page.page_number,
                    element_type=ElementType.PARAGRAPH,
                    text=UntrustedText(text),
                    reading_order=reading_order,
                    processing_method=ProcessingMethod.OCR,
                    created_at=now,
                    bounding_box=bbox,
                    confidence=conf / 100.0,
                )
            )
            reading_order += 1

        return elements
