"""Async engine factory, session factory, and FastAPI session dependency.

The engine is built once at application startup from DatabaseSettings and
stored in the Container. Request handlers obtain one AsyncSession per request
through the get_session dependency; they never touch the engine directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.configuration.settings import DatabaseSettings


def _normalise_url(raw: str) -> str:
    """Ensure the URL carries the psycopg async driver prefix.

    Bare postgresql:// and postgres:// URLs are missing the driver hint that
    SQLAlchemy needs to select psycopg3. postgresql+psycopg:// is left as-is.
    """
    for bare in ("postgresql://", "postgres://"):
        if raw.startswith(bare):
            return "postgresql+psycopg://" + raw[len(bare) :]
    return raw


def build_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Build an AsyncEngine from DatabaseSettings.

    Pool parameters (size, overflow, timeout) and SQL echo flag come from
    settings. The URL scheme is normalised to postgresql+psycopg:// so that
    psycopg3's async driver is always selected regardless of what the stored
    URL uses.
    """
    return create_async_engine(
        _normalise_url(settings.url.get_secret_value()),
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        echo=settings.echo_sql,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the given engine.

    expire_on_commit=False prevents attribute expiry after commit, which would
    otherwise trigger implicit lazy loads that are incompatible with async sessions.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one AsyncSession per request.

    The session is closed automatically when the request completes (or when an
    exception propagates out of the handler). Callers that need explicit
    transaction control call session.begin() themselves.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.container.session_factory
    async with factory() as session:
        yield session
