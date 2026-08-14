"""Trace ID middleware.

Assigns a UUID trace ID to every request, stores it in a ContextVar for the
duration of the request so that exception handlers can embed it in error bodies,
and echoes it back to the caller as the X-Trace-ID response header.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.application.observability.context import TraceContext

trace_id_ctx: ContextVar[str] = ContextVar("trace_id_ctx", default="")


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = str(uuid.uuid4())
        token = trace_id_ctx.set(trace_id)
        TraceContext.bind(trace_id=trace_id)
        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = trace_id
            return response
        finally:
            trace_id_ctx.reset(token)
