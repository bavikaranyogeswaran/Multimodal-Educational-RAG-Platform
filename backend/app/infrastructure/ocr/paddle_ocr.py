"""PaddleOCR PP-OCRv6 adapter — CPU-only text recognition over rendered page images.

Runs recognition in a thread because PaddleOCR is synchronous and CPU-bound. The
worker event loop runs heartbeats concurrently; blocking it would stall the heartbeat
and allow the job lease to expire while the work it covers is still running.

PaddleOCR downloads model weights on first use and then caches them locally.
Construction is therefore cheap; the first `extract_text` call takes longer.

Coordinate system
-----------------
PaddleOCR works in pixel space with the origin at the top-left of the image.
`DocumentElement` bounding boxes are in PDF user-space points (1/72 inch) with the
origin at the bottom-left. The conversion has two steps:

  1. Scale: multiply pixel coordinates by 72 / dpi.
  2. Flip: y_pdf = page_height_pts - y_pixel_pts.

The adapter is constructed with the same DPI that the page renderer uses, so the two
scales cancel out correctly.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import structlog

from app.domain.documents.entities import DocumentElement, DocumentPage
from app.domain.enums import ElementType, ProcessingMethod
from app.domain.errors import InvariantViolationError
from app.domain.values import BoundingBox, UntrustedText

_log = structlog.get_logger(__name__)

_POINTS_PER_INCH = 72.0


def _to_bbox(
    polygon: list[list[float]],
    *,
    page_height: float,
    dpi: int,
) -> BoundingBox | None:
    """Convert a PaddleOCR polygon (pixel, top-left origin) to a PDF BoundingBox.

    PaddleOCR returns four corners — [[x0,y0],[x1,y1],[x2,y2],[x3,y3]] — in pixel
    coordinates measured from the top-left of the rendered image. The conversion:

      - Takes the axis-aligned bounding box of the four corners, which handles tilted
        text without needing a rotated rectangle in the domain.
      - Scales from pixels to PDF points by multiplying by 72 / dpi.
      - Flips the y-axis from top-left to bottom-left origin.

    Returns None for a degenerate region (zero area or not enough points) so the
    caller can skip that result rather than passing an invalid object to the entity.
    """
    if not polygon or len(polygon) < 2:
        return None

    xs = [float(pt[0]) for pt in polygon]
    ys = [float(pt[1]) for pt in polygon]

    scale = _POINTS_PER_INCH / dpi
    x0 = min(xs) * scale
    x1 = max(xs) * scale

    # In pixel space, smaller y is closer to the image top (downward axis).
    y_top_pts = min(ys) * scale
    y_bottom_pts = max(ys) * scale

    # Flip to PDF bottom-left: the top of the box in pixels becomes the larger y in PDF.
    y0 = page_height - y_bottom_pts
    y1 = page_height - y_top_pts

    try:
        return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
    except InvariantViolationError:
        return None


class PaddleOcrAdapter:
    """OcrPort backed by PaddleOCR PP-OCRv6 on CPU.

    Constructed once at the composition root and shared across all OCR_PAGE jobs
    in the worker process. The underlying PaddleOCR engine is initialised on the
    first call and then reused; initialisation involves loading model weights from
    disk, which is slow enough that doing it per-call would be prohibitive.
    """

    def __init__(self, *, lang: str, dpi: int) -> None:
        self._lang = lang
        self._dpi = dpi
        self._engine: Any = None  # initialised lazily on first call

    def _get_engine(self) -> Any:
        if self._engine is None:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]

            self._engine = PaddleOCR(
                lang=self._lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            _log.info("paddle_ocr_engine_ready", lang=self._lang)
        return self._engine

    async def extract_text(
        self,
        image: bytes,
        *,
        page: DocumentPage,
    ) -> Sequence[DocumentElement]:
        """Extract text elements from a rendered page image.

        Every returned element is scoped to the page's user and Knowledge Base.
        Low-confidence results are included rather than dropped — the confidence is
        recorded on the element and the caller decides what to do with it.
        """
        elements = await asyncio.to_thread(self._extract_blocking, image, page)
        _log.info(
            "ocr_page_done",
            document_id=str(page.document_id),
            page_number=page.page_number,
            elements=len(elements),
        )
        return elements

    def _extract_blocking(
        self, image: bytes, page: DocumentPage
    ) -> list[DocumentElement]:
        """Run PaddleOCR synchronously and convert results to domain elements."""
        engine = self._get_engine()
        now = datetime.now(UTC)

        try:
            raw = engine.predict(image)
        except Exception:
            _log.exception(
                "ocr_engine_error",
                document_id=str(page.document_id),
                page_number=page.page_number,
            )
            return []

        elements: list[DocumentElement] = []
        reading_order = 0

        for page_result in raw or []:
            texts: list[str] = page_result.get("rec_texts", [])
            scores: list[float] = page_result.get("rec_scores", [])
            # PaddleOCR 3.x returns polygon corners as rec_polys; rec_boxes is the
            # axis-aligned rectangle. Prefer rec_polys for accuracy on rotated text.
            polys: list[Any] = page_result.get(
                "rec_polys", page_result.get("rec_boxes", [])
            )

            for text, score, poly in zip(texts, scores, polys):
                text = str(text).strip()
                if not text:
                    continue

                bbox = _to_bbox(poly, page_height=page.height, dpi=self._dpi)
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
                        confidence=float(score),
                    )
                )
                reading_order += 1

        return elements
