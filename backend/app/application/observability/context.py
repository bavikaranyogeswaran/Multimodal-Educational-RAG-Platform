"""Application-layer trace context.

Holds the trace ID and optional user ID for the current async task. Structlog
processors read from here to inject context fields on every log event without
threading IDs through call signatures.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Ctx:
    trace_id: str = ""
    user_id: str | None = None


_ctx_var: ContextVar[_Ctx | None] = ContextVar("trace_context", default=None)


class TraceContext:
    """Class-level namespace for binding and reading the current request context.

    Backed by a ContextVar so each asyncio Task sees its own isolated values;
    calling `bind()` inside one request never affects another.
    """

    @classmethod
    def bind(cls, *, trace_id: str | None = None, user_id: str | None = None) -> None:
        """Merge new values into the current task's context.

        Only the fields provided are updated; omitted fields carry forward from
        the current binding so a later `bind(user_id=...)` does not clear the
        trace ID set by the middleware.
        """
        current = _ctx_var.get()
        current_trace = "" if current is None else current.trace_id
        current_user: str | None = None if current is None else current.user_id
        _ctx_var.set(
            _Ctx(
                trace_id=trace_id if trace_id is not None else current_trace,
                user_id=user_id if user_id is not None else current_user,
            )
        )

    @classmethod
    def get(cls) -> dict[str, Any]:
        """Return the current context as a plain dict for structlog processors.

        `user_id` is omitted when it has not been bound so log events without
        an authenticated user do not carry a `user_id: null` field.
        """
        ctx = _ctx_var.get()
        if ctx is None:
            return {"trace_id": ""}
        result: dict[str, Any] = {"trace_id": ctx.trace_id}
        if ctx.user_id is not None:
            result["user_id"] = ctx.user_id
        return result
