"""Shared fixtures for integration tests against the live PostgreSQL database.

Tests are skipped automatically when TEST_DATABASE_URL is not set in the
environment. The db_session fixture gives each test an AsyncSession that is
bound to a transaction which rolls back after the test completes, leaving the
database unchanged regardless of what the test inserts or updates.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# The loop these tests need is settled in the root conftest, which runs first and
# applies it to every test rather than only to the ones that reach a real database.
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_URL_ENV = "TEST_DATABASE_URL"


def _normalise_url(raw: str) -> str:
    """Ensure the URL uses the psycopg3 async dialect."""
    for prefix in ("postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg" + raw[raw.index("://"):]
    return raw


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Normalised async URL for SQLAlchemy; skips the session if unset."""
    raw = os.getenv(_URL_ENV, "")
    if not raw:
        pytest.skip(f"{_URL_ENV} is not set — skipping integration tests")
    return _normalise_url(raw)


@pytest.fixture(scope="session")
def test_db_url_raw() -> str:
    """Raw URL as written in the environment, for subprocess-based tools (e.g. alembic)."""
    raw = os.getenv(_URL_ENV, "")
    if not raw:
        pytest.skip(f"{_URL_ENV} is not set — skipping integration tests")
    return raw


@pytest_asyncio.fixture
async def db_session(test_db_url: str) -> AsyncIterator[AsyncSession]:
    """Async session for one test, always rolled back on exit.

    Uses a direct connection so that session.flush() writes to the database
    within the open transaction but the outer rollback discards everything at
    the end of the test.
    """
    engine = create_async_engine(test_db_url, echo=False)
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
    await engine.dispose()
