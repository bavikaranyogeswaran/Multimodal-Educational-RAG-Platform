"""FastAPI application entry point.

The presentation layer only. Routes, middleware and error mapping are wired here;
retrieval, OCR and provider-specific logic live behind the domain ports.

Run with:  uv run uvicorn app.main:app --reload

On Windows the --reload matters for more than reloading. Uvicorn picks the proactor
event loop unless it is running with a subprocess, and psycopg refuses to open an async
connection on that loop, so a server started without it reaches startup and then fails
every query. Startup checks for this rather than letting it surface one request later.
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
from app.api.routers.conversations import router as conversations_router
from app.api.routers.documents import router as documents_router
from app.api.routers.graph import router as graph_router
from app.api.routers.knowledge_bases import router as knowledge_bases_router
from app.api.routers.memory import router as memory_router
from app.api.routers.study_content import router as study_content_router
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.infrastructure.auth.jwks import JwksClient
from app.infrastructure.models.warmup import warm_up_models
from app.infrastructure.observability.structlog_setup import configure_structlog
from app.runtime import explain_unusable_loop, running_loop_reaches_postgres

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

    # Checked rather than chosen: the server starts the loop and hands it over, so this
    # is the first moment the application can see which one it got. Saying so now costs
    # a startup rather than every query failing later with an error that describes the
    # loop and not how it came to be selected.
    if not running_loop_reaches_postgres():
        raise RuntimeError(explain_unusable_loop())

    _app.state.container = build_container(settings)
    _app.state.jwks_client = JwksClient(
        url=settings.supabase.jwks_url,
        cache_seconds=settings.supabase.jwks_cache_seconds,
    )
    if settings.model.warm_models_on_startup:
        await warm_up_models(_app.state.container.model_gateway)
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
app.include_router(knowledge_bases_router, prefix=API_PREFIX)
app.include_router(documents_router, prefix=API_PREFIX)
app.include_router(conversations_router, prefix=API_PREFIX)
app.include_router(graph_router, prefix=API_PREFIX)
app.include_router(memory_router, prefix=API_PREFIX)
app.include_router(study_content_router, prefix=API_PREFIX)


@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    """Liveness probe. Deliberately unauthenticated and free of dependency checks.

    Readiness — database, storage and model provider reachability — is a separate concern
    and gets its own endpoint alongside the observability middleware.
    """
    return {"status": "ok", "version": app.version}
