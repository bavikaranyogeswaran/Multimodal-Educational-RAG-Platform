"""Exception-to-HTTP mapping for the FastAPI application.

Call `register_exception_handlers(app)` once after the app is created. Every
domain error reaches an HTTP response through one of the handlers here; the
generic handler ensures an unrecognised exception still produces a 500 rather
than an empty connection close.

Security note: `ScopeViolationError` maps to 404, never to 403. A resource
another user owns must look identical to a resource that does not exist, so the
API cannot be used as an oracle for guessing identifiers. The violation is still
recorded as a security event in the log.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.api.middleware.trace import trace_id_ctx
from app.domain.errors import (
    AuthenticationError,
    InvariantViolationError,
    NotFoundError,
    ScopeViolationError,
    UploadValidationError,
)

_log = structlog.get_logger(__name__)


def _body(detail: str) -> dict[str, str]:
    return {"detail": detail, "trace_id": trace_id_ctx.get()}


def _http_exc_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=_body(detail),
        headers=getattr(exc, "headers", None),
    )


def _not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content=_body(str(exc)))


def _scope_violation_handler(_request: Request, exc: ScopeViolationError) -> JSONResponse:
    _log.warning(
        "scope_violation_intercepted",
        expected_user_id=str(exc.expected_user_id),
        expected_kb_id=str(exc.expected_knowledge_base_id),
    )
    return JSONResponse(status_code=404, content=_body("Not found"))


def _auth_error_handler(_request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=_body(str(exc)),
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invariant_handler(_request: Request, exc: InvariantViolationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_body(str(exc)))


def _upload_validation_handler(_request: Request, exc: UploadValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_body(str(exc)))


def _generic_handler(_request: Request, exc: Exception) -> JSONResponse:
    _log.error("unhandled_exception", exc_type=type(exc).__name__)
    return JSONResponse(status_code=500, content=_body("Internal server error"))


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exc_handler)  # type: ignore[arg-type]
    app.add_exception_handler(NotFoundError, _not_found_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ScopeViolationError, _scope_violation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AuthenticationError, _auth_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(InvariantViolationError, _invariant_handler)  # type: ignore[arg-type]
    app.add_exception_handler(UploadValidationError, _upload_validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _generic_handler)
