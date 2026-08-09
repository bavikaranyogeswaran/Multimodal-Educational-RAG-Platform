"""Alembic migration environment.

The database URL is read from application settings rather than alembic.ini so
that credentials stay out of ini files and off disk. The async engine uses
psycopg3 (the ``psycopg`` package) via the ``postgresql+psycopg`` dialect.

Run migrations from the ``backend/`` directory:

    uv run alembic upgrade head
    uv run alembic downgrade base
    uv run alembic revision --autogenerate -m "describe the change"
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.configuration.settings import Settings
from app.infrastructure.database.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    raw = Settings().database.url.get_secret_value()
    # Normalise to the psycopg3 async dialect understood by SQLAlchemy 2.x.
    # Supabase connection strings arrive as postgresql:// or postgres://.
    for prefix in ("postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg" + raw[raw.index("://"):]
    return raw


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    ini_section: dict[str, str] = dict(
        config.get_section(config.config_ini_section) or {}
    )
    ini_section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
