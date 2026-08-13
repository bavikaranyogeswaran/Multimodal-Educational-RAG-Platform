"""Shared fixtures for infrastructure unit tests.

The `sqlite_session` fixture provides an in-memory SQLite database for repositories
whose ORM models contain no PostgreSQL-specific column types. Only three tables are
created: knowledge_bases, documents, and document_pages — all of which use standard
SQL types (UUID stored as CHAR, DateTime, Boolean, etc.) that SQLite handles natively.

DocumentElementModel (ARRAY) and ChunkModel (Vector + ARRAY + TSVECTOR) are not
created in SQLite. Tests for those repository methods use AsyncMock sessions instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.database.base import Base
from app.infrastructure.database.models.document import DocumentModel, DocumentPageModel
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel


@pytest_asyncio.fixture
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    """Fresh in-memory SQLite session for each test.

    Knowledge-bases, documents, and document-pages are created; the session is
    disposed after the test completes, so state never leaks across tests.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    tables = [
        # Looked up by name rather than through `__table__`, which declares the looser
        # FromClause type that create_all does not accept.
        Base.metadata.tables[KnowledgeBaseModel.__tablename__],
        Base.metadata.tables[DocumentModel.__tablename__],
        Base.metadata.tables[DocumentPageModel.__tablename__],
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
