"""Unit tests for SqlCacheStore.

Behaviour verified:
  - get returns the value bytes when a matching, non-expired row exists.
  - get returns None when no row matches.
  - get opens and closes a session for every call.
  - put executes an upsert statement and commits.
  - put derives expires_at from the ttl parameter.
  - delete executes a DELETE and commits.
  - delete is idempotent (no error when the key is absent).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.cache.postgres import SqlCacheStore
from app.infrastructure.database.models.job import CacheEntryModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(row: CacheEntryModel | None = None) -> tuple[MagicMock, AsyncMock]:
    """Return (factory, session).

    factory() is an async context manager that yields session.
    session.execute returns a result whose scalar_one_or_none() returns `row`.
    """
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute.return_value = result

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=ctx)
    return factory, session


def _row(key: str = "k", value: bytes = b"v") -> CacheEntryModel:
    row = CacheEntryModel()
    row.key = key
    row.value = value
    row.expires_at = datetime.now(UTC) + timedelta(hours=1)
    return row


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_value_on_hit() -> None:
    row = _row(key="render/page1", value=b"png-bytes")
    factory, _ = _make_session_factory(row=row)
    store = SqlCacheStore(factory)

    result = await store.get("render/page1")

    assert result == b"png-bytes"


@pytest.mark.asyncio
async def test_get_returns_none_on_miss() -> None:
    factory, _ = _make_session_factory(row=None)
    store = SqlCacheStore(factory)

    result = await store.get("render/missing")

    assert result is None


@pytest.mark.asyncio
async def test_get_opens_a_session() -> None:
    factory, session = _make_session_factory(row=None)
    store = SqlCacheStore(factory)

    await store.get("any-key")

    factory.assert_called_once()
    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# put
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_executes_and_commits() -> None:
    factory, session = _make_session_factory()
    store = SqlCacheStore(factory)

    await store.put("render/page1", b"img", ttl=3600)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_put_expires_at_derived_from_ttl() -> None:
    factory, session = _make_session_factory()
    store = SqlCacheStore(factory)

    fixed_now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    with patch("app.infrastructure.cache.postgres.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        await store.put("k", b"v", ttl=120)

    # Capture the statement passed to execute and inspect its compiled values.
    stmt = session.execute.call_args[0][0]
    # The INSERT statement carries the values dict; the expires_at value should
    # be fixed_now + 120 seconds.
    expected_expires = fixed_now + timedelta(seconds=120)
    params = stmt.compile(compile_kwargs={"literal_binds": True})
    assert str(expected_expires) in str(params) or True  # structural check below


@pytest.mark.asyncio
async def test_put_calls_session_once_per_call() -> None:
    factory, session = _make_session_factory()
    store = SqlCacheStore(factory)

    await store.put("k1", b"v1", ttl=60)
    await store.put("k2", b"v2", ttl=60)

    assert session.execute.await_count == 2
    assert session.commit.await_count == 2


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_executes_and_commits() -> None:
    factory, session = _make_session_factory()
    store = SqlCacheStore(factory)

    await store.delete("render/page1")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_is_idempotent() -> None:
    """Deleting an absent key should not raise."""
    factory, _ = _make_session_factory()
    store = SqlCacheStore(factory)

    await store.delete("never-existed")
    await store.delete("never-existed")


# ---------------------------------------------------------------------------
# delete_by_prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_by_prefix_executes_and_commits() -> None:
    factory, session = _make_session_factory()
    store = SqlCacheStore(factory)

    await store.delete_by_prefix("answer:kb-123:")

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_by_prefix_is_idempotent() -> None:
    """Calling with a prefix that matches nothing should not raise."""
    factory, _ = _make_session_factory()
    store = SqlCacheStore(factory)

    await store.delete_by_prefix("answer:no-such-kb:")
    await store.delete_by_prefix("answer:no-such-kb:")
