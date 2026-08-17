"""Render pages to images, and cache them rather than store them.

Recognition works on pixels, so a page that cannot be read from its text layer has to be
drawn before anything can read it. The result is worth keeping for as long as the work
that needs it, and no longer: it can be produced again from the original at any time, and
storing it permanently would multiply what a document costs to keep for no lasting gain.
So renders go to a cache with a lifetime, and the original PDF stays the only thing that
is actually kept.

That is also why a render is addressed by what it is a render of. Asking for page four of
a document twice produces the same key, so the second request finds the first one's work
instead of repeating it, and a re-render replaces what was there rather than accumulating
beside it.

pypdfium2 is synchronous and drawing a page at recognition resolution is slow enough to
matter, so the work is handed to a thread for the same reason parsing is: the worker holds
its job lease with a heartbeat on this event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
from uuid import UUID

import pypdfium2 as pdfium
import structlog

from app.domain.errors import UploadValidationError
from app.domain.ports.adapters import CacheStore
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)

#: PDF user space is defined at 72 points to the inch, so this converts a target
#: resolution into the scale factor the renderer wants.
_POINTS_PER_INCH = 72.0


class PageRenderer:
    """Render a page to PNG, going through the cache on the way out and back.

    The cache is a `CacheStore` rather than the permanent store deliberately — see the
    module docstring. Its adapter already applies the render prefix, so keys here name
    only the page.
    """

    def __init__(self, cache: CacheStore, *, dpi: int, ttl_seconds: int) -> None:
        self._cache = cache
        self._dpi = dpi
        self._ttl_seconds = ttl_seconds

    async def render(
        self,
        data: bytes,
        *,
        page_number: int,
        document_id: UUID,
        scope: ScopeContext,
    ) -> bytes:
        """PNG bytes for one page, from the cache when they are already there.

        `page_number` is 1-indexed, matching how pages are numbered everywhere else and
        how a reader would refer to one.
        """
        key = _cache_key(scope, document_id, page_number)

        cached = await self._cache.get(key)
        if cached is not None:
            _log.debug("page_render_cache_hit", document_id=str(document_id), page=page_number)
            return cached

        image = await asyncio.to_thread(_render_blocking, data, page_number, self._dpi)
        await self._cache.put(key, image, ttl=self._ttl_seconds)
        _log.info(
            "page_rendered",
            document_id=str(document_id),
            page=page_number,
            dpi=self._dpi,
            bytes=len(image),
        )
        return image

    async def discard(
        self,
        *,
        page_number: int,
        document_id: UUID,
        scope: ScopeContext,
    ) -> None:
        """Drop a cached render, so the next request draws the page again.

        Needed when a document is reprocessed: the cached image is of the file as it was,
        and nothing about the key would change to say otherwise.
        """
        await self._cache.delete(_cache_key(scope, document_id, page_number))


def _cache_key(scope: ScopeContext, document_id: UUID, page_number: int) -> str:
    """Where a render lives, derived entirely from what it is a render of.

    Scoped like everything else, so one user's cached renders cannot be addressed by
    another even accidentally — a cache is still a place data sits.
    """
    return f"{scope.user_id}/{scope.knowledge_base_id}/{document_id}/p{page_number}.png"


def _render_blocking(data: bytes, page_number: int, dpi: int) -> bytes:
    """Draw one page. Runs on a worker thread.

    Loading is inside the guard as well as drawing: a file that cannot be opened at all
    fails there, and it is the same failure to the caller as one that cannot be drawn.
    """
    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:
        raise UploadValidationError(f"could not open PDF for rendering: {exc}") from exc

    with contextlib.closing(document):
        # Asked before the drawing guard below, so a page that was never there is
        # reported as such rather than as a drawing failure.
        page_count = len(document)
        if not 1 <= page_number <= page_count:
            raise UploadValidationError(
                f"page {page_number} is outside a document of {page_count} pages"
            )

        try:
            image = document[page_number - 1].render(scale=dpi / _POINTS_PER_INCH).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        except Exception as exc:
            raise UploadValidationError(
                f"could not render page {page_number}: {exc}"
            ) from exc
        return buffer.getvalue()
