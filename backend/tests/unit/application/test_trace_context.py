"""Unit tests for TraceContext.

All tests are async so each runs in a fresh asyncio event loop with a clean
ContextVar state — no ordering dependencies between tests.
"""

from __future__ import annotations

import asyncio

from app.application.observability.context import TraceContext


class TestTraceContext:
    async def test_default_trace_id_is_empty_string(self) -> None:
        assert TraceContext.get()["trace_id"] == ""

    async def test_get_excludes_user_id_before_it_is_bound(self) -> None:
        assert "user_id" not in TraceContext.get()

    async def test_bind_sets_trace_id(self) -> None:
        TraceContext.bind(trace_id="abc-123")
        assert TraceContext.get()["trace_id"] == "abc-123"

    async def test_bind_with_user_id_includes_it_in_result(self) -> None:
        TraceContext.bind(trace_id="t", user_id="user-42")
        ctx = TraceContext.get()
        assert ctx["user_id"] == "user-42"

    async def test_bind_user_id_preserves_existing_trace_id(self) -> None:
        TraceContext.bind(trace_id="original-trace")
        TraceContext.bind(user_id="late-user")
        assert TraceContext.get()["trace_id"] == "original-trace"

    async def test_bind_trace_id_preserves_existing_user_id(self) -> None:
        TraceContext.bind(trace_id="t", user_id="sticky-user")
        TraceContext.bind(trace_id="new-trace")
        assert TraceContext.get()["user_id"] == "sticky-user"

    async def test_binds_are_isolated_across_async_tasks(self) -> None:
        """One task's bind must not bleed into another task."""
        results: dict[str, str] = {}

        async def _set_and_get(name: str, trace_id: str) -> None:
            TraceContext.bind(trace_id=trace_id)
            await asyncio.sleep(0)
            results[name] = TraceContext.get()["trace_id"]

        await asyncio.gather(
            asyncio.create_task(_set_and_get("a", "trace-a")),
            asyncio.create_task(_set_and_get("b", "trace-b")),
        )
        assert results["a"] == "trace-a"
        assert results["b"] == "trace-b"
