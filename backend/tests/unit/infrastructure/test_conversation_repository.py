"""Tests for SqlConversationRepository against an in-memory SQLite database.

Covers CRUD for both Conversation and Message aggregates, scope isolation,
result ordering, the limit parameter on list_messages, and the evidence record
written for each answer. The SQLite session includes the knowledge_bases,
conversations, messages and conversation_retrieval_chunks tables. A KB row is
inserted before each test that saves a conversation, to satisfy the FK constraint.

Retrieval-chunk rows reference chunk ids that have no matching row, because the
chunks table carries PostgreSQL-specific column types and is not created here.
SQLite does not enforce foreign keys by default, so the reference is accepted and
these tests stay focused on what the repository writes.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations.entities import Conversation, Message
from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, MessageRole, MessageStatus, RetrieverKind
from app.domain.errors import ScopeViolationError
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, UntrustedText
from app.infrastructure.database.models.conversation import (
    ConversationRetrievalChunkModel,
    MessageCitationModel,
)
from app.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from app.infrastructure.database.repositories.conversation import SqlConversationRepository

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_scope(
    *,
    user_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
) -> ScopeContext:
    return ScopeContext(
        user_id=user_id or uuid.uuid4(),
        knowledge_base_id=kb_id or uuid.uuid4(),
    )


def _make_conv(
    scope: ScopeContext,
    *,
    title: str = "Test Conversation",
    age_seconds: int = 0,
) -> Conversation:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Conversation(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        title=title,
        created_at=ts,
        updated_at=ts,
    )


def _make_msg(
    scope: ScopeContext,
    conv_id: uuid.UUID,
    *,
    role: MessageRole = MessageRole.USER,
    age_seconds: int = 0,
) -> Message:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return Message(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        role=role,
        status=MessageStatus.RECEIVED,
        content=UntrustedText("Hello, tutor!"),
        created_at=ts,
        updated_at=ts,
    )


def _make_evidence(
    scope: ScopeContext,
    *,
    rank: int = 0,
    rerank_score: float | None = -10.5,
    fusion_score: float | None = None,
) -> Evidence:
    return Evidence(
        label=EvidenceLabel(rank + 1),
        chunk=Chunk(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT,
            text=UntrustedText("Backpropagation computes gradients layer by layer."),
            token_count=9,
            ordinal=rank,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=datetime.now(UTC),
        ),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=rank,
        rerank_score=rerank_score,
        fusion_score=fusion_score,
    )


async def _citation_rows(
    session: AsyncSession, message_id: uuid.UUID
) -> list[MessageCitationModel]:
    stmt = (
        select(MessageCitationModel)
        .where(MessageCitationModel.message_id == message_id)
        .order_by(MessageCitationModel.citation_order)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _retrieval_rows(
    session: AsyncSession, message_id: uuid.UUID
) -> list[ConversationRetrievalChunkModel]:
    stmt = (
        select(ConversationRetrievalChunkModel)
        .where(ConversationRetrievalChunkModel.message_id == message_id)
        .order_by(ConversationRetrievalChunkModel.rank)
    )
    return list((await session.execute(stmt)).scalars().all())


def _repo(scope: ScopeContext, session: AsyncSession) -> SqlConversationRepository:
    return SqlConversationRepository(scope=scope, session=session)


async def _save_kb(scope: ScopeContext, session: AsyncSession) -> None:
    now = datetime.now(UTC)
    session.add(
        KnowledgeBaseModel(
            id=scope.knowledge_base_id,
            user_id=scope.user_id,
            name="KB",
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    async def test_returns_matching_conversation(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        await _repo(scope, sqlite_session).save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope, conv.id)

        assert result is not None
        assert result.id == conv.id
        assert result.title == conv.title

    async def test_returns_none_when_absent(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get(scope, uuid.uuid4())
        assert result is None

    async def test_user_isolation_blocks_cross_user_read(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        conv = _make_conv(scope_a)
        await _repo(scope_a, sqlite_session).save(scope_a, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope_b, sqlite_session).get(scope_b, conv.id)
        assert result is None


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    async def test_insert_then_get(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        await _repo(scope, sqlite_session).save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await _repo(scope, sqlite_session).get(scope, conv.id)
        assert result is not None
        assert result.id == conv.id

    async def test_update_existing(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope, title="Original")
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        updated = replace(conv, title="Renamed", updated_at=datetime.now(UTC))
        await repo.save(scope, updated)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get(scope, conv.id)
        assert result is not None
        assert result.title == "Renamed"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    async def test_returns_all_conversations_for_scope(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        for i in range(3):
            await repo.save(scope, _make_conv(scope, title=f"Conv {i}"))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list(scope)
        assert len(results) == 3

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, _make_conv(scope, title="Older", age_seconds=60))
        await repo.save(scope, _make_conv(scope, title="Newer", age_seconds=0))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list(scope)
        assert results[0].title == "Newer"
        assert results[1].title == "Older"

    async def test_user_isolation(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        await _save_kb(scope_b, sqlite_session)
        await _repo(scope_a, sqlite_session).save(scope_a, _make_conv(scope_a))
        await _repo(scope_b, sqlite_session).save(scope_b, _make_conv(scope_b))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await _repo(scope_a, sqlite_session).list(scope_a)
        assert len(results) == 1
        assert results[0].user_id == scope_a.user_id


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_removes_conversation(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        await repo.delete(scope, conv.id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await repo.get(scope, conv.id) is None

    async def test_delete_is_scoped_by_user(self, sqlite_session: AsyncSession) -> None:
        scope_a = _make_scope()
        scope_b = _make_scope()
        await _save_kb(scope_a, sqlite_session)
        conv = _make_conv(scope_a)
        await _repo(scope_a, sqlite_session).save(scope_a, conv)
        await sqlite_session.flush()

        await _repo(scope_b, sqlite_session).delete(scope_b, conv.id)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await _repo(scope_a, sqlite_session).get(scope_a, conv.id) is not None


# ---------------------------------------------------------------------------
# get_message / save_message
# ---------------------------------------------------------------------------


class TestMessage:
    async def test_save_then_get_message(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_message(scope, msg.id)
        assert result is not None
        assert result.id == msg.id
        assert result.content == UntrustedText("Hello, tutor!")

    async def test_get_message_returns_none_when_absent(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        result = await _repo(scope, sqlite_session).get_message(scope, uuid.uuid4())
        assert result is None

    async def test_save_message_update(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        now = datetime.now(UTC)
        updated = msg.mark_processing(now=now)
        await repo.save_message(scope, updated)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        result = await repo.get_message(scope, msg.id)
        assert result is not None
        assert result.status == MessageStatus.PROCESSING


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------


class TestListMessages:
    async def test_returns_messages_for_conversation(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        for _ in range(3):
            await repo.save_message(scope, _make_msg(scope, conv.id))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv.id)
        assert len(results) == 3

    async def test_orders_newest_first(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        await repo.save_message(scope, _make_msg(scope, conv.id, age_seconds=60))
        await repo.save_message(scope, _make_msg(scope, conv.id, age_seconds=0))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv.id)
        assert results[0].created_at > results[1].created_at

    async def test_respects_limit(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        for i in range(5):
            await repo.save_message(
                scope, _make_msg(scope, conv.id, age_seconds=5 - i)
            )
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv.id, limit=3)
        assert len(results) == 3

    async def test_excludes_other_conversations(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv_a = _make_conv(scope, title="A")
        conv_b = _make_conv(scope, title="B")
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv_a)
        await repo.save(scope, conv_b)
        await sqlite_session.flush()
        await repo.save_message(scope, _make_msg(scope, conv_a.id))
        await repo.save_message(scope, _make_msg(scope, conv_b.id))
        await sqlite_session.flush()
        sqlite_session.expire_all()

        results = await repo.list_messages(scope, conv_a.id)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# save_retrieval_chunks
# ---------------------------------------------------------------------------


class TestSaveRetrievalChunks:
    async def test_writes_one_row_per_evidence_item(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        evidence = [_make_evidence(scope, rank=i) for i in range(3)]
        await repo.save_retrieval_chunks(scope, msg.id, evidence)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _retrieval_rows(sqlite_session, msg.id)
        assert len(rows) == 3

    async def test_stores_chunk_ids_and_ranks(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        evidence = [_make_evidence(scope, rank=i) for i in range(3)]
        await repo.save_retrieval_chunks(scope, msg.id, evidence)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _retrieval_rows(sqlite_session, msg.id)
        assert [r.chunk_id for r in rows] == [e.chunk.id for e in evidence]
        assert [r.rank for r in rows] == [0, 1, 2]

    async def test_stores_rerank_score_when_present(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        evidence = [_make_evidence(scope, rerank_score=-8.25, fusion_score=0.016)]
        await repo.save_retrieval_chunks(scope, msg.id, evidence)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _retrieval_rows(sqlite_session, msg.id)
        assert rows[0].score == pytest.approx(-8.25)

    async def test_falls_back_to_fusion_score(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        # Reranking did not run, so fusion is the last stage that scored this chunk.
        evidence = [_make_evidence(scope, rerank_score=None, fusion_score=0.016)]
        await repo.save_retrieval_chunks(scope, msg.id, evidence)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _retrieval_rows(sqlite_session, msg.id)
        assert rows[0].score == pytest.approx(0.016)

    async def test_falls_back_to_zero_when_no_stage_scored(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        evidence = [_make_evidence(scope, rerank_score=None, fusion_score=None)]
        await repo.save_retrieval_chunks(scope, msg.id, evidence)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _retrieval_rows(sqlite_session, msg.id)
        assert rows[0].score == pytest.approx(0.0)

    async def test_empty_evidence_writes_nothing(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        await repo.save_retrieval_chunks(scope, msg.id, [])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await _retrieval_rows(sqlite_session, msg.id) == []

    async def test_rewriting_the_same_message_replaces_rather_than_duplicates(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await sqlite_session.flush()

        evidence = [_make_evidence(scope, rank=0, rerank_score=-9.0)]
        await repo.save_retrieval_chunks(scope, msg.id, evidence)
        await sqlite_session.flush()

        rescored = [replace(evidence[0], rerank_score=-4.0)]
        await repo.save_retrieval_chunks(scope, msg.id, rescored)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _retrieval_rows(sqlite_session, msg.id)
        assert len(rows) == 1
        assert rows[0].score == pytest.approx(-4.0)

    async def test_separate_messages_keep_separate_records(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        await _save_kb(scope, sqlite_session)
        conv = _make_conv(scope)
        repo = _repo(scope, sqlite_session)
        await repo.save(scope, conv)
        await sqlite_session.flush()
        first = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT, age_seconds=60)
        second = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, first)
        await repo.save_message(scope, second)
        await sqlite_session.flush()

        await repo.save_retrieval_chunks(scope, first.id, [_make_evidence(scope)])
        await repo.save_retrieval_chunks(
            scope, second.id, [_make_evidence(scope, rank=i) for i in range(2)]
        )
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert len(await _retrieval_rows(sqlite_session, first.id)) == 1
        assert len(await _retrieval_rows(sqlite_session, second.id)) == 2


# ---------------------------------------------------------------------------
# Scope guard — a call carrying someone else's scope never reaches the session
# ---------------------------------------------------------------------------


class TestConversationScopeGuard:
    async def test_get_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.get(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save(_make_scope(), _make_conv(scope))
        session.merge.assert_not_called()

    async def test_list_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list(_make_scope())
        session.execute.assert_not_called()

    async def test_delete_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.delete(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_get_message_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.get_message(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_message_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_message(_make_scope(), _make_msg(scope, uuid.uuid4()))
        session.merge.assert_not_called()

    async def test_list_messages_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)
        with pytest.raises(ScopeViolationError):
            await repo.list_messages(_make_scope(), uuid.uuid4())
        session.execute.assert_not_called()

    async def test_save_retrieval_chunks_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_retrieval_chunks(
                _make_scope(), uuid.uuid4(), [_make_evidence(scope)]
            )
        session.merge.assert_not_called()

    async def test_save_citations_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)
        with pytest.raises(ScopeViolationError):
            await repo.save_citations(
                _make_scope(), uuid.uuid4(), [_make_evidence(scope).to_citation(order=0)]
            )
        session.merge.assert_not_called()


# ---------------------------------------------------------------------------
# save_citations
# ---------------------------------------------------------------------------


class TestSaveCitations:
    """What the answer actually used, as opposed to what it was shown."""

    @staticmethod
    async def _assistant_message(
        scope: ScopeContext, session: AsyncSession
    ) -> tuple[SqlConversationRepository, Message]:
        await _save_kb(scope, session)
        conv = _make_conv(scope)
        repo = _repo(scope, session)
        await repo.save(scope, conv)
        await session.flush()
        msg = _make_msg(scope, conv.id, role=MessageRole.ASSISTANT)
        await repo.save_message(scope, msg)
        await session.flush()
        return repo, msg

    async def test_writes_one_row_per_citation(self, sqlite_session: AsyncSession) -> None:
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)
        citations = [
            _make_evidence(scope, rank=i).to_citation(order=i) for i in range(3)
        ]

        await repo.save_citations(scope, msg.id, citations)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert len(await _citation_rows(sqlite_session, msg.id)) == 3

    async def test_stores_the_label_unbracketed(self, sqlite_session: AsyncSession) -> None:
        """The brackets are how the label is printed, not what it is."""
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)

        await repo.save_citations(
            scope, msg.id, [_make_evidence(scope, rank=0).to_citation(order=0)]
        )
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert (await _citation_rows(sqlite_session, msg.id))[0].label == "S1"

    async def test_keeps_the_order_the_answer_argues_in(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)
        citations = [
            _make_evidence(scope, rank=i).to_citation(order=i) for i in range(4)
        ]

        await repo.save_citations(scope, msg.id, citations)
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _citation_rows(sqlite_session, msg.id)
        assert [r.citation_order for r in rows] == [0, 1, 2, 3]
        assert [r.chunk_id for r in rows] == [c.chunk_id for c in citations]

    async def test_copies_the_location_rather_than_pointing_at_the_chunk(
        self, sqlite_session: AsyncSession
    ) -> None:
        """Reprocessing rewrites chunks. The row has to say where the passage was when it
        was cited, or a rewritten chunk silently changes what a past answer claimed."""
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)
        evidence = _make_evidence(scope)
        evidence = replace(
            evidence,
            chunk=replace(
                evidence.chunk,
                page_start=67,
                page_end=67,
                bounding_box=BoundingBox(10, 20, 110, 60),
                content_hash="sha256:abc123",
            ),
        )

        await repo.save_citations(scope, msg.id, [evidence.to_citation(order=0)])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        row = (await _citation_rows(sqlite_session, msg.id))[0]
        assert row.page_number == 67
        assert row.chunk_type == ChunkType.TEXT.value
        assert row.evidence_hash == "sha256:abc123"
        assert (row.bounding_box_x0, row.bounding_box_y1) == (10, 60)

    async def test_a_passage_without_a_box_still_records_its_page(
        self, sqlite_session: AsyncSession
    ) -> None:
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)

        await repo.save_citations(
            scope, msg.id, [_make_evidence(scope).to_citation(order=0)]
        )
        await sqlite_session.flush()
        sqlite_session.expire_all()

        row = (await _citation_rows(sqlite_session, msg.id))[0]
        assert row.bounding_box_x0 is None
        assert row.page_number > 0

    async def test_an_answer_citing_nothing_writes_nothing(
        self, sqlite_session: AsyncSession
    ) -> None:
        """An abstaining or rejected answer cited no passage, and an empty set of rows is
        the honest record of that — not a missing one."""
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)

        await repo.save_citations(scope, msg.id, [])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        assert await _citation_rows(sqlite_session, msg.id) == []

    async def test_regenerating_overwrites_rather_than_colliding(
        self, sqlite_session: AsyncSession
    ) -> None:
        """The composite key would reject a second write for the same message; merge is
        what lets an answer be regenerated without first deleting its old citations."""
        scope = _make_scope()
        repo, msg = await self._assistant_message(scope, sqlite_session)
        first = _make_evidence(scope, rank=0).to_citation(order=0)

        await repo.save_citations(scope, msg.id, [first])
        await sqlite_session.flush()
        second = _make_evidence(scope, rank=0).to_citation(order=0)
        await repo.save_citations(scope, msg.id, [second])
        await sqlite_session.flush()
        sqlite_session.expire_all()

        rows = await _citation_rows(sqlite_session, msg.id)
        assert len(rows) == 1
        assert rows[0].chunk_id == second.chunk_id
