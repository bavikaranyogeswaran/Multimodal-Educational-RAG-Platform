"""Fallback OCR adapter — chains a primary and an optional secondary engine.

The secondary (vision-language enhanced) engine fires only when the primary
result is poor: either no elements were extracted at all, or the average
confidence across all elements falls below the configured threshold.

This gate keeps the expensive VL path rare. §15 of the specification caps it
at 20% of pages on any representative document (NFR-PERF-17) — exceeding that
fraction is a signal that the page classifier is miscalibrated, not that the
document is unusual. The adapter enforces the quality condition, not the
fraction; tracking the fraction is a monitoring concern.

If no secondary is supplied, the primary result is returned unchanged even when
poor. This lets the caller disable the VL path at the composition root (for
example when the heavy model is not installed) without changing the fallback
logic.
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from app.domain.documents.entities import DocumentElement, DocumentPage
from app.domain.ports.adapters import OcrPort

_log = structlog.get_logger(__name__)


def _needs_fallback(
    elements: Sequence[DocumentElement], *, confidence_threshold: float
) -> bool:
    """Return True when the primary result is poor enough to warrant VL fallback.

    Two conditions — either is sufficient:
      1. The primary returned no elements (the page appears blank to OCR).
      2. The mean confidence across all elements with a recorded score is below
         the threshold, meaning the engine was uncertain about most of what it
         read.

    Elements without a confidence score do not contribute to the mean; a result
    of all-None confidences is treated as acceptable (return False) rather than
    assumed poor.
    """
    if not elements:
        return True
    confidences = [e.confidence for e in elements if e.confidence is not None]
    if not confidences:
        return False
    return sum(confidences) / len(confidences) < confidence_threshold


class FallbackOcrAdapter:
    """OcrPort that tries the primary and falls back to the secondary on poor results.

    The secondary is optional. When absent the primary result is returned
    unchanged, even if it was poor, so the caller can wire `secondary=None` to
    disable the VL path without changing any other code.
    """

    def __init__(
        self,
        primary: OcrPort,
        secondary: OcrPort | None,
        *,
        confidence_threshold: float,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._confidence_threshold = confidence_threshold

    async def extract_text(
        self, image: bytes, *, page: DocumentPage
    ) -> Sequence[DocumentElement]:
        elements = await self._primary.extract_text(image, page=page)

        if self._secondary is None:
            return elements

        if not _needs_fallback(elements, confidence_threshold=self._confidence_threshold):
            return elements

        _log.info(
            "ocr_vl_fallback_triggered",
            document_id=str(page.document_id),
            page_number=page.page_number,
            primary_elements=len(elements),
            avg_confidence=(
                sum(e.confidence for e in elements if e.confidence is not None)
                / max(1, sum(1 for e in elements if e.confidence is not None))
            )
            if elements
            else None,
        )
        return await self._secondary.extract_text(image, page=page)
