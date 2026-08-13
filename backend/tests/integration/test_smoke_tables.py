"""Smoke insert-and-retrieve tests against the live PostgreSQL database.

One representative row is inserted and read back for every migration that
creates data tables. Each test runs in a rolled-back transaction so the
database is unchanged after the suite finishes.

Migration coverage:
    0002 — knowledge_bases, documents, document_pages
    0003 — chunks  (embedding column is nullable — no vector value required)
    0005 — conversations, memory_facts
    0006 — graph_entities
    0007 — processing_jobs

RLS coverage (0008):
    knowledge_bases row inserted as the superuser is invisible to the anon
    role because auth.uid() returns NULL and user_id = NULL is never true.

Column source of truth: alembic migrations (not ORM models), since the
migrations define the actual schema that runs in production.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

pytestmark = pytest.mark.integration

_TS = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _uid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# 0002 — knowledge_bases
# ---------------------------------------------------------------------------


async def test_knowledge_base_roundtrip(db_session: AsyncSession) -> None:
    kb_id = _uid()
    user_id = _uid()
    await db_session.execute(
        text(
            "INSERT INTO knowledge_bases (id, user_id, name, created_at, updated_at) "
            "VALUES (:id, :user_id, :name, :ts, :ts)"
        ),
        {"id": kb_id, "user_id": user_id, "name": "Smoke KB", "ts": _TS},
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT name FROM knowledge_bases WHERE id = :id"),
            {"id": kb_id},
        )
    ).one()
    assert row.name == "Smoke KB"


# ---------------------------------------------------------------------------
# 0002 — documents + document_pages
#
# document_pages has no timestamp columns (see migration 0002).
# chunks FK is to documents.id, not document_pages.id.
# ---------------------------------------------------------------------------


async def test_document_and_page_roundtrip(db_session: AsyncSession) -> None:
    """Covers documents (with timestamps) and document_pages (without timestamps)."""
    user_id = _uid()
    kb_id = _uid()
    doc_id = _uid()
    page_id = _uid()

    await db_session.execute(
        text(
            "INSERT INTO knowledge_bases (id, user_id, name, created_at, updated_at) "
            "VALUES (:id, :user_id, :name, :ts, :ts)"
        ),
        {"id": kb_id, "user_id": user_id, "name": "Doc KB", "ts": _TS},
    )
    await db_session.execute(
        text(
            "INSERT INTO documents "
            "(id, user_id, knowledge_base_id, filename, content_type, byte_size, "
            " storage_key, created_at, updated_at) "
            "VALUES (:id, :uid, :kb, :fn, :ct, :sz, :sk, :ts, :ts)"
        ),
        {
            "id": doc_id,
            "uid": user_id,
            "kb": kb_id,
            "fn": "lecture.pdf",
            "ct": "application/pdf",
            "sz": 1024,
            "sk": "uploads/lecture.pdf",
            "ts": _TS,
        },
    )
    # document_pages has no created_at / updated_at columns.
    await db_session.execute(
        text(
            "INSERT INTO document_pages "
            "(id, user_id, knowledge_base_id, document_id, page_number, kind, width, height) "
            "VALUES (:id, :uid, :kb, :doc, :pg, :kind, :w, :h)"
        ),
        {
            "id": page_id,
            "uid": user_id,
            "kb": kb_id,
            "doc": doc_id,
            "pg": 1,
            "kind": "TEXT",
            "w": 595.0,
            "h": 842.0,
        },
    )
    await db_session.flush()

    doc_row = (
        await db_session.execute(
            text("SELECT filename FROM documents WHERE id = :id"),
            {"id": doc_id},
        )
    ).one()
    assert doc_row.filename == "lecture.pdf"

    page_row = (
        await db_session.execute(
            text("SELECT page_number FROM document_pages WHERE id = :id"),
            {"id": page_id},
        )
    ).one()
    assert page_row.page_number == 1


# ---------------------------------------------------------------------------
# 0003 — chunks
#
# FK is to documents.id (not document_pages). Required non-nullable columns
# with no server default: chunk_type, text, token_count, ordinal, page_start,
# page_end. heading_path / language / index_version have server defaults.
# embedding is nullable — no pgvector value needed.
# chunks has created_at but NO updated_at.
# ---------------------------------------------------------------------------


async def test_chunk_roundtrip(db_session: AsyncSession) -> None:
    user_id = _uid()
    kb_id = _uid()
    doc_id = _uid()
    chunk_id = _uid()

    await db_session.execute(
        text(
            "INSERT INTO knowledge_bases (id, user_id, name, created_at, updated_at) "
            "VALUES (:id, :user_id, :name, :ts, :ts)"
        ),
        {"id": kb_id, "user_id": user_id, "name": "Chunk KB", "ts": _TS},
    )
    await db_session.execute(
        text(
            "INSERT INTO documents "
            "(id, user_id, knowledge_base_id, filename, content_type, byte_size, "
            " storage_key, created_at, updated_at) "
            "VALUES (:id, :uid, :kb, :fn, :ct, :sz, :sk, :ts, :ts)"
        ),
        {
            "id": doc_id,
            "uid": user_id,
            "kb": kb_id,
            "fn": "lecture.pdf",
            "ct": "application/pdf",
            "sz": 1024,
            "sk": "uploads/lecture.pdf",
            "ts": _TS,
        },
    )
    # chunks has created_at but no updated_at.
    await db_session.execute(
        text(
            "INSERT INTO chunks "
            "(id, user_id, knowledge_base_id, document_id, "
            " chunk_type, text, token_count, ordinal, page_start, page_end, created_at) "
            "VALUES (:id, :uid, :kb, :doc, :ctype, :txt, :tc, :ord, :ps, :pe, :ts)"
        ),
        {
            "id": chunk_id,
            "uid": user_id,
            "kb": kb_id,
            "doc": doc_id,
            "ctype": "NARRATIVE",
            "txt": "Newton's first law states that an object at rest stays at rest.",
            "tc": 14,
            "ord": 0,
            "ps": 1,
            "pe": 1,
            "ts": _TS,
        },
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT chunk_type, token_count FROM chunks WHERE id = :id"),
            {"id": chunk_id},
        )
    ).one()
    assert row.chunk_type == "NARRATIVE"
    assert row.token_count == 14


# ---------------------------------------------------------------------------
# 0005 — conversations
# ---------------------------------------------------------------------------


async def test_conversation_roundtrip(db_session: AsyncSession) -> None:
    user_id = _uid()
    kb_id = _uid()
    conv_id = _uid()

    await db_session.execute(
        text(
            "INSERT INTO knowledge_bases (id, user_id, name, created_at, updated_at) "
            "VALUES (:id, :user_id, :name, :ts, :ts)"
        ),
        {"id": kb_id, "user_id": user_id, "name": "Conv KB", "ts": _TS},
    )
    await db_session.execute(
        text(
            "INSERT INTO conversations "
            "(id, user_id, knowledge_base_id, title, created_at, updated_at) "
            "VALUES (:id, :uid, :kb, :title, :ts, :ts)"
        ),
        {"id": conv_id, "uid": user_id, "kb": kb_id, "title": "Session 1", "ts": _TS},
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT title FROM conversations WHERE id = :id"),
            {"id": conv_id},
        )
    ).one()
    assert row.title == "Session 1"


# ---------------------------------------------------------------------------
# 0005 — memory_facts
#
# memory_facts stores user_id and knowledge_base_id as denormalized columns
# without FK constraints. No parent row is required.
# ---------------------------------------------------------------------------


async def test_memory_fact_roundtrip(db_session: AsyncSession) -> None:
    fact_id = _uid()

    await db_session.execute(
        text(
            "INSERT INTO memory_facts "
            "(id, user_id, knowledge_base_id, memory_type, content, "
            " provenance, status, valid_from, created_at, updated_at) "
            "VALUES (:id, :uid, :kb, :mtype, :content, :prov, :status, :ts, :ts, :ts)"
        ),
        {
            "id": fact_id,
            "uid": _uid(),
            "kb": _uid(),
            "mtype": "DECLARATIVE",
            "content": "F = ma",
            "prov": 1,
            "status": "ACTIVE",
            "ts": _TS,
        },
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT content, status FROM memory_facts WHERE id = :id"),
            {"id": fact_id},
        )
    ).one()
    assert row.content == "F = ma"
    assert row.status == "ACTIVE"


# ---------------------------------------------------------------------------
# 0006 — graph_entities
# ---------------------------------------------------------------------------


async def test_graph_entity_roundtrip(db_session: AsyncSession) -> None:
    user_id = _uid()
    kb_id = _uid()
    entity_id = _uid()

    await db_session.execute(
        text(
            "INSERT INTO knowledge_bases (id, user_id, name, created_at, updated_at) "
            "VALUES (:id, :user_id, :name, :ts, :ts)"
        ),
        {"id": kb_id, "user_id": user_id, "name": "Graph KB", "ts": _TS},
    )
    await db_session.execute(
        text(
            "INSERT INTO graph_entities "
            "(id, user_id, knowledge_base_id, entity_type, name, created_at, updated_at) "
            "VALUES (:id, :uid, :kb, :etype, :name, :ts, :ts)"
        ),
        {
            "id": entity_id,
            "uid": user_id,
            "kb": kb_id,
            "etype": "CONCEPT",
            "name": "Kinetic Energy",
            "ts": _TS,
        },
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT name, entity_type FROM graph_entities WHERE id = :id"),
            {"id": entity_id},
        )
    ).one()
    assert row.name == "Kinetic Energy"
    assert row.entity_type == "CONCEPT"


# ---------------------------------------------------------------------------
# 0007 — processing_jobs
#
# processing_jobs has no FK constraints — insertable without any parent rows.
# ---------------------------------------------------------------------------


async def test_processing_job_roundtrip(db_session: AsyncSession) -> None:
    job_id = _uid()
    kb_id = _uid()

    await db_session.execute(
        text(
            "INSERT INTO processing_jobs "
            "(id, job_type, priority, status, attempt_count, max_attempts, "
            " payload, created_at, updated_at) "
            "VALUES (:id, :jtype, :prio, :status, 0, 3, CAST(:payload AS jsonb), :ts, :ts)"
        ),
        {
            "id": job_id,
            "jtype": "DOCUMENT_INGESTION",
            "prio": 2,
            "status": "PENDING",
            "payload": f'{{"knowledge_base_id": "{kb_id}"}}',
            "ts": _TS,
        },
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            text("SELECT job_type, status FROM processing_jobs WHERE id = :id"),
            {"id": job_id},
        )
    ).one()
    assert row.job_type == "DOCUMENT_INGESTION"
    assert row.status == "PENDING"


# ---------------------------------------------------------------------------
# 0008 — RLS: superuser inserts are invisible to the anon role
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_rls_blocks_anonymous_access(test_db_url: str) -> None:
    """A row inserted as the superuser is not visible to the anon role.

    The knowledge_bases RLS policy requires user_id = auth.uid(). Under the
    anon role, auth.uid() returns NULL, so user_id = NULL is always false and
    no rows are returned regardless of what was inserted.

    Uses a direct connection (not db_session) so SET LOCAL ROLE and the
    subsequent rollback are on the same connection object.
    """
    user_id = _uid()
    kb_id = _uid()

    engine = create_async_engine(test_db_url, echo=False)
    count_as_anon: int = -1

    async with engine.connect() as conn:
        trans = await conn.begin()

        await conn.execute(
            text(
                "INSERT INTO knowledge_bases "
                "(id, user_id, name, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :ts, :ts)"
            ),
            {"id": kb_id, "user_id": user_id, "name": "RLS Test KB", "ts": _TS},
        )

        # Row must be visible to the superuser (who bypasses RLS by default).
        visible_as_super = (
            await conn.execute(
                text("SELECT count(*) FROM knowledge_bases WHERE id = :id"),
                {"id": kb_id},
            )
        ).scalar()
        assert visible_as_super == 1, "Row must be visible before role switch"

        # Switch to anon within this transaction — auth.uid() returns NULL.
        await conn.execute(text("SET LOCAL ROLE anon"))

        count_as_anon = (
            await conn.execute(
                text("SELECT count(*) FROM knowledge_bases WHERE id = :id"),
                {"id": kb_id},
            )
        ).scalar()

        await trans.rollback()

    await engine.dispose()

    assert count_as_anon == 0, (
        f"RLS policy did not block anon access — got {count_as_anon} row(s). "
        "Check that the knowledge_bases_user_isolation policy is in place."
    )
