"""Shared fixtures for infrastructure unit tests.

The `sqlite_session` fixture provides an in-memory SQLite database for repositories
whose ORM models contain no PostgreSQL-specific column types. The following tables are
created: knowledge_bases, documents, document_pages, conversations, messages,
conversation_retrieval_chunks, memory_facts, graph_entities, and graph_relationships —
all standard SQL types.

DocumentElementModel (ARRAY) and ChunkModel (Vector + ARRAY + TSVECTOR) are not
created in SQLite. Tests for those repository methods use AsyncMock sessions instead.
ProcessingJobModel (JSONB) is also excluded; all job tests use AsyncMock sessions.

SQLite does not enforce foreign keys by default, so FK references to the excluded
tables (e.g. chunks) in graph models are accepted at DDL time without error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.database.base import Base
from app.infrastructure.database.models.conversation import (
    ConversationModel,
    ConversationRetrievalChunkModel,
    MemoryFactModel,
    MessageModel,
)
from app.infrastructure.database.models.document import DocumentModel, DocumentPageModel
from app.infrastructure.database.models.graph import GraphEntityModel, GraphRelationshipModel
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel


@pytest_asyncio.fixture
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    """Fresh in-memory SQLite session for each test.

    All SQLite-compatible tables are created; the session is disposed after the test
    completes so state never leaks across tests. SQLAlchemy sorts the tables by FK
    dependency before issuing CREATE TABLE statements.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    tables = [
        # Looked up by name rather than through `__table__`, which declares the looser
        # FromClause type that create_all does not accept.
        Base.metadata.tables[KnowledgeBaseModel.__tablename__],
        Base.metadata.tables[DocumentModel.__tablename__],
        Base.metadata.tables[DocumentPageModel.__tablename__],
        Base.metadata.tables[ConversationModel.__tablename__],
        Base.metadata.tables[MessageModel.__tablename__],
        Base.metadata.tables[ConversationRetrievalChunkModel.__tablename__],
        Base.metadata.tables[MemoryFactModel.__tablename__],
        Base.metadata.tables[GraphEntityModel.__tablename__],
        Base.metadata.tables[GraphRelationshipModel.__tablename__],
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()
