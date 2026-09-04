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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.middleware.errors import register_exception_handlers
from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.middleware.trace import TraceIDMiddleware
from app.api.routers.conversations import router as conversations_router
from app.api.routers.documents import router as documents_router
from app.api.routers.graph import router as graph_router
from app.api.routers.knowledge_bases import router as knowledge_bases_router
from app.api.routers.memory import router as memory_router
from app.api.routers.study_content import router as study_content_router
from app.configuration.settings import Settings, get_settings
from app.configuration.wire import build_container
from app.infrastructure.auth.jwks import JwksClient
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.models.warmup import warm_up_models
from app.infrastructure.observability.structlog_setup import configure_structlog
from app.runtime import explain_unusable_loop, running_loop_reaches_postgres

API_PREFIX = "/api/v1"
_settings = get_settings()
_log = structlog.get_logger(__name__)


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
    _app.state.generation_semaphore = asyncio.Semaphore(settings.model.max_concurrent_generations)
    _app.state.user_generation_semaphores: dict[str, asyncio.Semaphore] = {}
    _app.state.jwks_client = JwksClient(
        url=settings.supabase.jwks_url,
        cache_seconds=settings.supabase.jwks_cache_seconds,
    )
    # Fetch the signing keys now rather than on the first authenticated request. Building
    # them inside a request handler makes that request fail, so the cost is paid here where
    # nothing is waiting on it.
    await _app.state.jwks_client.warm_up()
    if settings.model.warm_models_on_startup:
        await warm_up_models(_app.state.container.model_gateway)
    await _report_stale_indexes(_app.state.container.session_factory, settings)
    yield


async def _report_stale_indexes(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Say which Knowledge Bases are not reading from the version this build writes.

    A mismatch is what happens when the embedding model is reconfigured and no rebuild is
    run, and it has no symptom of its own: everything keeps working, and documents added
    afterwards are simply never found. Uploads are refused while it lasts, but a refusal
    only reaches whoever tries next. Saying it at startup reaches whoever restarted the
    server, which is usually the same person who changed the setting.

    Best-effort. This is a diagnostic, and a diagnostic that can stop the server from
    starting is worse than the condition it reports.
    """
    try:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    sa.select(KnowledgeBaseModel.id, KnowledgeBaseModel.active_index_version)
                    .where(
                        KnowledgeBaseModel.active_index_version != settings.embedding.index_version
                    )
                    .order_by(KnowledgeBaseModel.created_at)
                )
            ).all()
    except Exception:
        _log.warning("stale_index_check_failed", exc_info=True)
        return

    if not rows:
        return
    _log.warning(
        "knowledge_bases_need_reindexing",
        written_version=settings.embedding.index_version,
        count=len(rows),
        knowledge_bases=[
            {"id": str(kb_id), "active_index_version": active} for kb_id, active in rows
        ],
    )


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
    # Without this the trace header is set on every response and readable on none of
    # them: a browser hands script only the handful of headers it considers simple
    # unless the server names the rest. It survives a same-origin setup, so the gap
    # stays invisible in development and takes the identifier out of exactly the
    # production errors somebody would want to look up.
    expose_headers=["X-Trace-ID"],
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
