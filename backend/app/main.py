"""FastAPI application entry point.

The presentation layer only. Routes, middleware and error mapping are wired here;
retrieval, OCR and provider-specific logic live behind the domain ports.

Run with:  uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.errors import register_exception_handlers
from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.middleware.trace import TraceIDMiddleware
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.infrastructure.auth.jwks import JwksClient
from app.infrastructure.observability.structlog_setup import configure_structlog

API_PREFIX = "/api/v1"
_settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown.

    The dependency container and the JWKS client are built here and stored on
    app.state. Request handlers retrieve them through FastAPI dependencies rather
    than importing global state. Model warm-up and adapter connection pools hang
    off this context when their phases land.
    """
    settings = get_settings()
    configure_structlog(settings)
    _app.state.container = build_container(settings)
    _app.state.jwks_client = JwksClient(
        url=settings.supabase.jwks_url,
        cache_seconds=settings.supabase.jwks_cache_seconds,
    )
    yield


app = FastAPI(
    title="Multimodal Educational Tutor RAG",
    description="Private, student-facing, multimodal retrieval-augmented generation platform.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url=f"{API_PREFIX}/openapi.json",
)

# Middleware is applied inside-out: first-added runs outermost on requests.
# TraceID is outermost so the trace ID is in the ContextVar before any inner
# middleware or route handler runs.
app.add_middleware(TraceIDMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.app.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    """Liveness probe. Deliberately unauthenticated and free of dependency checks.

    Readiness — database, storage and model provider reachability — is a separate concern
    and gets its own endpoint alongside the observability middleware.
    """
    return {"status": "ok", "version": app.version}
