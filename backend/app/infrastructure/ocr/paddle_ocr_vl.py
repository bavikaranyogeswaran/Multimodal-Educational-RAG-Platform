"""PaddleOCR VL adapter — orientation-aware OCR for difficult pages.

This is the same PP-OCRv6 engine as the primary adapter, but with three
preprocessing stages enabled:

  - Document orientation classification: detects and corrects pages that were
    scanned upside-down or sideways.
  - Page unwarping: corrects curved or folded pages before recognition.
  - Textline orientation: handles individual text lines that are tilted or
    rotated on an otherwise upright page.

These stages add latency (roughly 3-5× the primary adapter) and are therefore
reserved for pages where the primary result was poor — empty or averaged below
the confidence threshold. The FallbackOcrAdapter in the same package applies
that gate; this module only provides the engine.
"""

from __future__ import annotations

from app.infrastructure.ocr.paddle_ocr import PaddleOcrAdapter


def PaddleOcrVlAdapter(*, lang: str, dpi: int) -> PaddleOcrAdapter:
    """Return a PaddleOcrAdapter with VL preprocessing enabled."""
    return PaddleOcrAdapter(lang=lang, dpi=dpi, use_vl=True)
