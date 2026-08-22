"""Crop a figure region from a PDF page.

Renders the requested page using pypdfium2 (same renderer and DPI as the page cache)
and crops the result to the bounding box the parser recorded. The crop is returned as
PNG bytes; the caller is responsible for uploading it to object storage.

Coordinate system note: pdfplumber records bounding boxes in PDF user-space points
(origin at the bottom-left corner of the page, y increasing upward). pypdfium2 renders
with the origin at the top-left (standard image convention, y increasing downward), so
the y coordinates must be flipped before cropping.
"""

from __future__ import annotations

import asyncio
import contextlib
import io

import pypdfium2 as pdfium
import structlog

from app.domain.values import BoundingBox

_log = structlog.get_logger(__name__)

_POINTS_PER_INCH = 72.0


class FigureCropper:
    """Renders a page and crops it to a figure's bounding box.

    Constructed once per process with the target DPI; individual crop calls
    are stateless and safe to call concurrently.
    """

    def __init__(self, *, dpi: int) -> None:
        self._dpi = dpi

    async def crop(
        self,
        data: bytes,
        *,
        page_number: int,
        page_height: float,
        bounding_box: BoundingBox,
    ) -> bytes:
        """PNG bytes for the bounding-box region on the given page.

        Runs the blocking render on a thread so the event loop is not stalled.
        `page_number` is 1-indexed; `page_height` is in PDF points.
        """
        return await asyncio.to_thread(
            _crop_blocking, data, page_number, page_height, bounding_box, self._dpi
        )


def _crop_blocking(
    data: bytes,
    page_number: int,
    page_height: float,
    bounding_box: BoundingBox,
    dpi: int,
) -> bytes:
    """Render and crop synchronously. Runs on a worker thread."""
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ValueError(f"could not open PDF for crop rendering: {exc}") from exc

    with contextlib.closing(document):
        scale = dpi / _POINTS_PER_INCH

        try:
            image = document[page_number - 1].render(scale=scale).to_pil()
        except Exception as exc:
            raise ValueError(
                f"could not render page {page_number} for cropping: {exc}"
            ) from exc

        # Convert bounding box from PDF pts (origin bottom-left) to pixel
        # coordinates (origin top-left), clamped to image bounds.
        left = max(0, int(bounding_box.x0 * scale))
        top = max(0, int((page_height - bounding_box.y1) * scale))
        right = min(image.width, int(bounding_box.x1 * scale))
        bottom = min(image.height, int((page_height - bounding_box.y0) * scale))

        if right <= left or bottom <= top:
            raise ValueError(
                f"bounding box {bounding_box!r} maps to a degenerate crop region "
                f"({left}, {top}, {right}, {bottom}) at {dpi} DPI"
            )

        cropped = image.crop((left, top, right, bottom))
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()
