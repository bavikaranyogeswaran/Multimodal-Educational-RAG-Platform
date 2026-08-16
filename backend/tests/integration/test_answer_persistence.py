"""Integration test: the writes made after the request ends actually reach PostgreSQL.

Every other test covering this path asserts against a mocked repository, which is
precisely the layer at which a missing commit is invisible. The bug this step fixes —
a handler writing into a session that is discarded when the response finishes — passes
every one of them. Only reading the rows back on a different connection can tell the
difference between "the use case called save" and "the row is there".

So the shape here is deliberate: one connection runs the turn, a second one, opened
afterwards and sharing nothing with it, looks for what should have been left behind.

Requires TEST_DATABASE_URL. Run with: uv run pytest -m integration
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.domain.documents.chunks import Chunk
from app.domain.enums import (
    ChunkType,
    DocumentStatus,
    MessageRole,
    MessageStatus,
    RetrieverKind,
)
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.unit_of_work import build_conversation_unit_of_work

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixture: a seeded knowledge base, conversation, document and chunk
# ---------------------------------------------------------------------------


class _Seed:
    def __init__(
        self,
        engine: AsyncEngine,
        scope: ScopeContext,
        conversation_id: uuid.UUID,
        chunk_id: uuid.UUID,
    ) -> None:
        self.engine = engine
        self.scope = scope
        self.conversation_id = conversation_id
        self.chunk_id = chunk_id
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def seed(test_db_url: str) -> AsyncIterator[_Seed]:
    """Insert the rows the turn depends on, then remove them afterwards.

    Committed rather than rolled back, because the code under test opens its own
    sessions and would not see an uncommitted outer transaction. Teardown deletes the
    knowledge base and lets the schema's cascades take the rest.
    """
    engine = create_async_engine(test_db_url, echo=False)
    user_id, kb_id = uuid.uuid4(), uuid.uuid4()
    conversation_id, document_id, chunk_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO knowledge_bases (id, user_id, name, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :now, :now)"
            ),
            {"id": kb_id, "user_id": user_id, "name": "Integration KB", "now": now},
        )
        await conn.execute(
            text(
                "INSERT INTO conversations "
                "(id, user_id, knowledge_base_id, title, created_at, updated_at) "
                "VALUES (:id, :user_id, :kb_id, :title, :now, :now)"
            ),
            {
                "id": conversation_id,
                "user_id": user_id,
                "kb_id": kb_id,
                "title": "Integration conversation",
                "now": now,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO documents (id, user_id, knowledge_base_id, filename, "
                "storage_key, content_type, byte_size, status, "
                "created_at, updated_at) "
                "VALUES (:id, :user_id, :kb_id, :filename, :storage_key, :content_type, "
                ":byte_size, :status, :now, :now)"
            ),
            {
                "id": document_id,
                "user_id": user_id,
                "kb_id": kb_id,
                "filename": "integration.pdf",
                "storage_key": f"{user_id}/{kb_id}/{document_id}/original.pdf",
                "content_type": "application/pdf",
                "byte_size": 1024,
                "status": DocumentStatus.COMPLETED.value,
                "now": now,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO chunks (id, user_id, knowledge_base_id, document_id, "
                "chunk_type, text, token_count, ordinal, page_start, page_end, "
                "index_version, created_at) "
                "VALUES (:id, :user_id, :kb_id, :document_id, :chunk_type, :text, "
                ":token_count, :ordinal, 1, 1, 1, :now)"
            ),
            {
                "id": chunk_id,
                "user_id": user_id,
                "kb_id": kb_id,
                "document_id": document_id,
                "chunk_type": ChunkType.TEXT.value,
                "text": "Backpropagation computes gradients layer by layer.",
                "token_count": 9,
                "ordinal": 0,
                "now": now,
            },
        )

    scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
    try:
        yield _Seed(engine, scope, conversation_id, chunk_id)
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM knowledge_bases WHERE id = :id"), {"id": kb_id}
            )
        await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence(seed: _Seed) -> Evidence:
    return Evidence(
        label=EvidenceLabel(1),
        chunk=Chunk(
            id=seed.chunk_id,
            user_id=seed.scope.user_id,
            knowledge_base_id=seed.scope.knowledge_base_id,
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT,
            text=UntrustedText("Backpropagation computes gradients layer by layer."),
            token_count=9,
            ordinal=0,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=datetime.now(UTC),
        ),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=0,
        rerank_score=-9.5,
    )


async def _run_turn(seed: _Seed, *, tokens: list[str]) -> None:
    """Answer one question end to end, consuming the stream to completion."""
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(return_value=[_evidence(seed)])

    async def _gen() -> AsyncIterator[str]:
        for token in tokens:
            yield token

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(return_value=_gen())

    use_case = AnswerUseCase(
        retrieve=retrieve,
        conversation_uow=build_conversation_unit_of_work(seed.session_factory, seed.scope),
        model_gateway=gateway,
    )
    stream = await use_case.execute(
        AnswerCommand(
            scope=seed.scope,
            conversation_id=seed.conversation_id,
            query="What is backpropagation?",
        )
    )
    async for _ in stream:
        pass


async def _rows(seed: _Seed, sql: str, params: dict[str, object]) -> list[RowMapping]:
    """Read on a connection opened after the turn finished, sharing nothing with it."""
    async with seed.engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).mappings().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnswerReachesTheDatabase:
    async def test_question_row_is_committed(self, seed: _Seed) -> None:
        await _run_turn(seed, tokens=["Gradients", " flow", " backwards."])

        rows = await _rows(
            seed,
            "SELECT role, status, content FROM messages "
            "WHERE conversation_id = :cid AND role = :role",
            {"cid": seed.conversation_id, "role": MessageRole.USER.value},
        )

        assert len(rows) == 1
        assert rows[0]["content"] == "What is backpropagation?"
        assert rows[0]["status"] == MessageStatus.RECEIVED.value

    async def test_answer_row_is_committed(self, seed: _Seed) -> None:
        await _run_turn(seed, tokens=["Gradients", " flow", " backwards."])

        rows = await _rows(
            seed,
            "SELECT status, content FROM messages "
            "WHERE conversation_id = :cid AND role = :role",
            {"cid": seed.conversation_id, "role": MessageRole.ASSISTANT.value},
        )

        # Written after the response finished streaming — the case the request-scoped
        # session could not have kept.
        assert len(rows) == 1
        assert rows[0]["content"] == "Gradients flow backwards."
        assert rows[0]["status"] == MessageStatus.COMPLETED.value

    async def test_evidence_record_is_committed(self, seed: _Seed) -> None:
        await _run_turn(seed, tokens=["An", " answer."])

        rows = await _rows(
            seed,
            "SELECT crc.chunk_id, crc.rank, crc.score "
            "FROM conversation_retrieval_chunks crc "
            "JOIN messages m ON m.id = crc.message_id "
            "WHERE m.conversation_id = :cid",
            {"cid": seed.conversation_id},
        )

        assert len(rows) == 1
        assert rows[0]["chunk_id"] == seed.chunk_id
        assert rows[0]["rank"] == 0
        assert rows[0]["score"] == pytest.approx(-9.5)

    async def test_evidence_record_points_at_the_answer(self, seed: _Seed) -> None:
        await _run_turn(seed, tokens=["An", " answer."])

        rows = await _rows(
            seed,
            "SELECT m.role FROM conversation_retrieval_chunks crc "
            "JOIN messages m ON m.id = crc.message_id "
            "WHERE m.conversation_id = :cid",
            {"cid": seed.conversation_id},
        )

        # Citation validation joins from the answer, so this is the direction that has
        # to hold in the schema, not only in the use case that wrote it.
        assert [row["role"] for row in rows] == [MessageRole.ASSISTANT.value]

    async def test_failed_generation_still_leaves_both_rows(self, seed: _Seed) -> None:
        retrieve = AsyncMock()
        retrieve.execute = AsyncMock(return_value=[_evidence(seed)])

        async def _failing() -> AsyncIterator[str]:
            yield "The answer is"
            raise RuntimeError("provider dropped the connection")

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(return_value=_failing())

        use_case = AnswerUseCase(
            retrieve=retrieve,
            conversation_uow=build_conversation_unit_of_work(seed.session_factory, seed.scope),
            model_gateway=gateway,
        )
        stream = await use_case.execute(
            AnswerCommand(
                scope=seed.scope,
                conversation_id=seed.conversation_id,
                query="What is backpropagation?",
            )
        )
        with pytest.raises(RuntimeError):
            async for _ in stream:
                pass

        rows = await _rows(
            seed,
            "SELECT role, status FROM messages WHERE conversation_id = :cid ORDER BY created_at",
            {"cid": seed.conversation_id},
        )

        assert [(r["role"], r["status"]) for r in rows] == [
            (MessageRole.USER.value, MessageStatus.RECEIVED.value),
            (MessageRole.ASSISTANT.value, MessageStatus.FAILED.value),
        ]
