"""PostgreSQL-backed CacheStore for regenerable content.

Uses the UNLOGGED `cache_entries` table (created in migration 2.7). UNLOGGED
skips WAL, so writes are fast and rows are discarded on an unclean shutdown —
exactly right for a cache. pg_cron sweeps expired rows once per minute.

This adapter is wired when R2 is not configured (local dev / CI). In
production the R2CacheAdapter takes precedence; both implement the same
CacheStore protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.sql import delete as sa_delete

from app.infrastructure.database.models.job import CacheEntryModel

_log = structlog.get_logger(__name__)


class SqlCacheStore:
    """CacheStore backed by the UNLOGGED `cache_entries` PostgreSQL table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, key: str) -> bytes | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            result = await session.execute(
                select(CacheEntryModel).where(
                    CacheEntryModel.key == key,
                    # Accept rows with no expiry or whose expiry is in the future.
                    (CacheEntryModel.expires_at.is_(None))
                    | (CacheEntryModel.expires_at > now),
                )
            )
            row = result.scalar_one_or_none()
        if row is None:
            _log.debug("cache_miss", key=key)
            return None
        _log.debug("cache_hit", key=key)
        return row.value

    async def put(self, key: str, data: bytes, *, ttl: int) -> None:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        async with self._session_factory() as session:
            stmt = (
                pg_insert(CacheEntryModel)
                .values(key=key, value=data, expires_at=expires_at)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": data, "expires_at": expires_at},
                )
            )
            await session.execute(stmt)
            await session.commit()
        _log.debug("cache_put", key=key, ttl=ttl)

    async def delete(self, key: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                sa_delete(CacheEntryModel).where(CacheEntryModel.key == key)
            )
            await session.commit()
        _log.debug("cache_delete", key=key)
