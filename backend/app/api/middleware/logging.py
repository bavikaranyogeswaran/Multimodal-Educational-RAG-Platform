"""Request logging middleware.

Emits one structured log line per request: method, path, status code, duration,
and trace ID. The Authorization header value is deliberately excluded — it must
never appear in log output.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.middleware.trace import trace_id_ctx

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            trace_id=trace_id_ctx.get(),
        )
        return response
