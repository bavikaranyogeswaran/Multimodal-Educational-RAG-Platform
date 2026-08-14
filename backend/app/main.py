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

from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.infrastructure.auth.jwks import JwksClient

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown.

    The dependency container and the JWKS client are built here and stored on
    app.state. Request handlers retrieve them through FastAPI dependencies rather
    than importing global state. Model warm-up and adapter connection pools hang
    off this context when their phases land.
    """
    settings = get_settings()
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


@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    """Liveness probe. Deliberately unauthenticated and free of dependency checks.

    Readiness — database, storage and model provider reachability — is a separate concern
    and gets its own endpoint alongside the observability middleware.
    """
    return {"status": "ok", "version": app.version}
