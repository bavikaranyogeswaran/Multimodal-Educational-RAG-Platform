"""Tests for PageRenderer against the committed PDF fixtures.

Two properties carry the weight here. Renders are cached rather than stored, so the cache
has to be consulted before the work is done and written to after — a renderer that drew
the page every time would pass any test that only checked the bytes. And the key has to be
derived entirely from what the render is of, because that is what makes asking twice cheap
and what keeps one user's renders out of another's reach.

A real cache adapter is exercised separately in the R2 tests; here it is a small in-memory
stand-in, so what is being tested is the renderer's use of a cache rather than the cache.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest

from app.domain.errors import UploadValidationError
from app.domain.scope import ScopeContext
from app.infrastructure.rendering.page_renderer import PageRenderer

_FIXTURES = pathlib.Path(__file__).parents[2] / "fixtures" / "pdfs"

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_DOCUMENT_ID = uuid.uuid4()

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _pdf(name: str = "native_text_sample") -> bytes:
    return (_FIXTURES / f"{name}.pdf").read_bytes()


class _FakeCache:
    """An in-memory CacheStore that records what was asked of it."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.gets: list[str] = []
        self.puts: list[str] = []
        self.deletes: list[str] = []

    async def get(self, key: str) -> bytes | None:
        self.gets.append(key)
        return self.entries.get(key)

    async def put(self, key: str, data: bytes, *, ttl: int) -> None:
        self.puts.append(key)
        self.entries[key] = data
        self.ttls[key] = ttl

    async def delete(self, key: str) -> None:
        self.deletes.append(key)
        self.entries.pop(key, None)


def _renderer(
    cache: _FakeCache | None = None, *, dpi: int = 100, ttl_seconds: int = 604_800
) -> tuple[PageRenderer, _FakeCache]:
    store = cache or _FakeCache()
    return PageRenderer(store, dpi=dpi, ttl_seconds=ttl_seconds), store


async def _render(
    renderer: PageRenderer, page_number: int = 1, name: str = "native_text_sample"
) -> bytes:
    return await renderer.render(
        _pdf(name), page_number=page_number, document_id=_DOCUMENT_ID, scope=_SCOPE
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering:
    async def test_a_page_renders_to_png(self) -> None:
        renderer, _ = _renderer()
        image = await _render(renderer)
        assert image.startswith(_PNG_MAGIC)

    async def test_each_page_renders_differently(self) -> None:
        """Two pages of the same document carry different text, so identical bytes would
        mean the page number was being ignored."""
        renderer, _ = _renderer()
        first = await _render(renderer, 1)
        second = await _render(renderer, 2)
        assert first != second

    async def test_resolution_changes_the_result(self) -> None:
        low, _ = _renderer(dpi=50)
        high, _ = _renderer(dpi=150)
        assert len(await _render(low)) < len(await _render(high))

    async def test_a_page_beyond_the_document_is_refused(self) -> None:
        renderer, _ = _renderer()
        with pytest.raises(UploadValidationError, match="outside a document"):
            await _render(renderer, 99)

    async def test_page_zero_is_refused(self) -> None:
        """Pages are numbered from one everywhere else, and zero is a caller's mistake
        rather than a request for the last page."""
        renderer, _ = _renderer()
        with pytest.raises(UploadValidationError):
            await _render(renderer, 0)

    async def test_an_unreadable_file_is_refused(self) -> None:
        renderer, _ = _renderer()
        with pytest.raises(UploadValidationError):
            await renderer.render(
                b"not a PDF", page_number=1, document_id=_DOCUMENT_ID, scope=_SCOPE
            )


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    async def test_the_cache_is_consulted_before_rendering(self) -> None:
        renderer, cache = _renderer()
        await _render(renderer)
        assert cache.gets, "the renderer drew the page without asking the cache first"

    async def test_a_render_is_written_to_the_cache(self) -> None:
        renderer, cache = _renderer()
        image = await _render(renderer)
        assert list(cache.entries.values()) == [image]

    async def test_a_second_request_is_served_from_the_cache(self) -> None:
        renderer, cache = _renderer()
        first = await _render(renderer)
        second = await _render(renderer)
        assert first == second
        assert len(cache.puts) == 1, "the page was drawn twice"

    async def test_a_cached_render_is_returned_unchanged(self) -> None:
        renderer, cache = _renderer()
        key = f"{_SCOPE.user_id}/{_SCOPE.knowledge_base_id}/{_DOCUMENT_ID}/p1.png"
        cache.entries[key] = b"a previous render"
        assert await _render(renderer) == b"a previous render"

    async def test_the_configured_lifetime_is_applied(self) -> None:
        renderer, cache = _renderer(ttl_seconds=3600)
        await _render(renderer)
        assert set(cache.ttls.values()) == {3600}

    async def test_an_expired_entry_causes_a_fresh_render(self) -> None:
        """An expiring cache returns nothing rather than stale bytes, and the renderer
        treats that exactly as it treats never having drawn the page."""
        renderer, cache = _renderer()
        await _render(renderer)
        cache.entries.clear()  # what expiry looks like from here
        image = await _render(renderer)
        assert image.startswith(_PNG_MAGIC)
        assert len(cache.puts) == 2


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


class TestCacheKeys:
    async def test_the_key_is_derived_from_the_page_it_renders(self) -> None:
        renderer, cache = _renderer()
        await _render(renderer, 2)
        assert cache.puts == [
            f"{_SCOPE.user_id}/{_SCOPE.knowledge_base_id}/{_DOCUMENT_ID}/p2.png"
        ]

    async def test_different_pages_use_different_keys(self) -> None:
        renderer, cache = _renderer()
        await _render(renderer, 1)
        await _render(renderer, 2)
        assert len(set(cache.puts)) == 2

    async def test_the_key_is_scoped(self) -> None:
        """A cache is still a place data sits, so one user's renders must not be
        addressable by another even by accident."""
        renderer, cache = _renderer()
        await _render(renderer)
        key = cache.puts[0]
        assert str(_SCOPE.user_id) in key
        assert str(_SCOPE.knowledge_base_id) in key

    async def test_the_key_is_stable_across_calls(self) -> None:
        """Which is what makes asking twice cheap rather than merely correct."""
        renderer, cache = _renderer()
        await _render(renderer)
        cache.entries.clear()
        await _render(renderer)
        assert cache.puts[0] == cache.puts[1]

    async def test_re_rendering_replaces_rather_than_accumulates(self) -> None:
        renderer, cache = _renderer()
        await _render(renderer)
        cache.entries.clear()
        await _render(renderer)
        assert len(cache.entries) == 1


# ---------------------------------------------------------------------------
# Discarding
# ---------------------------------------------------------------------------


class TestDiscard:
    async def test_a_discarded_render_is_removed(self) -> None:
        renderer, cache = _renderer()
        await _render(renderer)
        await renderer.discard(page_number=1, document_id=_DOCUMENT_ID, scope=_SCOPE)
        assert cache.entries == {}

    async def test_discarding_targets_the_same_key_rendering_used(self) -> None:
        """Two ways of naming the same page that could drift apart, so they are pinned
        against each other rather than each against a literal."""
        renderer, cache = _renderer()
        await _render(renderer, 2)
        await renderer.discard(page_number=2, document_id=_DOCUMENT_ID, scope=_SCOPE)
        assert cache.deletes == cache.puts

    async def test_the_next_request_draws_the_page_again(self) -> None:
        renderer, cache = _renderer()
        await _render(renderer)
        await renderer.discard(page_number=1, document_id=_DOCUMENT_ID, scope=_SCOPE)
        await _render(renderer)
        assert len(cache.puts) == 2


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestRenderingDoesNotBlockTheLoop:
    async def test_other_tasks_run_while_a_render_is_in_flight(self) -> None:
        """The worker holds its job lease with a heartbeat on this same loop, and drawing
        a page at recognition resolution is slow enough for that to matter."""
        import asyncio

        ticks = 0

        async def _ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0)
                ticks += 1

        ticker = asyncio.create_task(_ticker())
        try:
            renderer, _ = _renderer(dpi=150)
            await _render(renderer)
        finally:
            ticker.cancel()

        assert ticks > 0
