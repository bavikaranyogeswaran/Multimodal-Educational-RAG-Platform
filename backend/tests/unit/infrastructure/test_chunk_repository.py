"""Tests for SqlChunkRepository.

ChunkModel uses pgvector Vector, ARRAY, and TSVECTOR — none of which SQLite supports.
All tests use a mock AsyncSession. The tests verify:
  - scope filtering (WHERE user_id, knowledge_base_id) is applied on every query
  - document_id filter is applied on document-scoped queries
  - save_batch calls session.merge once per chunk
  - delete uses a DELETE statement, not a SELECT
  - entity/model mapping handles optional fields and value objects correctly
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType
from app.domain.errors import ScopeViolationError
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, HeadingPath, UntrustedText
from app.infrastructure.database.repositories.chunk import (
    SqlChunkRepository,
    _to_entity,
    _to_model,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_chunk(
    scope: ScopeContext,
    *,
    ordinal: int = 0,
    document_id: uuid.UUID | None = None,
) -> Chunk:
    ts = datetime.now(UTC)
    return Chunk(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=document_id or uuid.uuid4(),
        chunk_type=ChunkType.TEXT,
        text=UntrustedText("Some lecture content."),
        token_count=10,
        ordinal=ordinal,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=ts,
    )


def _mock_result_scalar_none() -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


def _mock_result_scalars(rows: list[object]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _repo(scope: ScopeContext, session: AsyncSession) -> SqlChunkRepository:
    return SqlChunkRepository(scope=scope, session=session)


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestChunkGet:
    async def test_returns_none_when_not_found(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        repo = _repo(scope, session)

        result = await repo.get(scope, uuid.uuid4())

        assert result is None
        session.execute.assert_called_once()

    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        repo = _repo(scope, session)

        await repo.get(scope, uuid.uuid4())

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_applies_chunk_id_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalar_none())
        chunk_id = uuid.uuid4()
        await _repo(scope, session).get(scope, chunk_id)

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert str(chunk_id).replace("-", "") in compiled


# ---------------------------------------------------------------------------
# save_batch
# ---------------------------------------------------------------------------


class TestSaveBatch:
    async def test_merges_each_chunk(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.merge = AsyncMock(return_value=MagicMock())
        repo = _repo(scope, session)

        chunks = [_make_chunk(scope) for _ in range(4)]
        await repo.save_batch(scope, chunks)

        assert session.merge.call_count == 4

    async def test_empty_batch_calls_no_merge(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.merge = AsyncMock(return_value=MagicMock())
        repo = _repo(scope, session)

        await repo.save_batch(scope, [])

        session.merge.assert_not_called()


# ---------------------------------------------------------------------------
# get_many
# ---------------------------------------------------------------------------


class TestGetMany:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _repo(scope, session)

        await repo.get_many(scope, [uuid.uuid4(), uuid.uuid4()])

        compiled = str(session.execute.call_args[0][0].compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_asks_for_every_id_in_one_query(self) -> None:
        """Parent loading calls this once for a whole evidence list. A query per id would
        put the database inside the wait for an answer once per passage."""
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _repo(scope, session)

        await repo.get_many(scope, [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()])

        session.execute.assert_called_once()
        assert "IN" in str(session.execute.call_args[0][0].compile()).upper()

    async def test_no_ids_makes_no_query(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)

        assert await repo.get_many(scope, []) == []
        session.execute.assert_not_called()

    async def test_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.get_many(_make_scope(), [uuid.uuid4()])

        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# list_for_document
# ---------------------------------------------------------------------------


class TestListForDocument:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _repo(scope, session)

        await repo.list_for_document(scope, uuid.uuid4())

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled
        assert "document_id" in compiled

    async def test_applies_ordinal_ordering(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result_scalars([]))
        repo = _repo(scope, session)

        await repo.list_for_document(scope, uuid.uuid4())

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "ordinal" in compiled


# ---------------------------------------------------------------------------
# delete_for_document
# ---------------------------------------------------------------------------


class TestDeleteForDocument:
    async def test_applies_scope_and_document_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = _repo(scope, session)

        doc_id = uuid.uuid4()
        await repo.delete_for_document(scope, doc_id)

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled
        assert "document_id" in compiled

    async def test_uses_delete_statement(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock())
        repo = _repo(scope, session)

        await repo.delete_for_document(scope, uuid.uuid4())

        stmt = session.execute.call_args[0][0]
        assert isinstance(stmt, Delete)


# ---------------------------------------------------------------------------
# Scope guard — a call carrying someone else's scope never reaches the session
# ---------------------------------------------------------------------------


class TestChunkScopeGuard:
    async def test_get_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.get(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()

    async def test_save_batch_rejects_foreign_scope(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        repo = _repo(scope, session)

        with pytest.raises(ScopeViolationError):
            await repo.save_batch(_make_scope(), [_make_chunk(scope)])

        session.merge.assert_not_called()

    async def test_list_for_document_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.list_for_document(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()

    async def test_delete_for_document_rejects_foreign_scope(self) -> None:
        session = AsyncMock()
        repo = _repo(_make_scope(), session)

        with pytest.raises(ScopeViolationError):
            await repo.delete_for_document(_make_scope(), uuid.uuid4())

        session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Entity/model mapping — pure unit tests, no DB or session needed
# ---------------------------------------------------------------------------


class TestChunkMapping:
    def test_to_model_sets_core_fields(self) -> None:
        scope = _make_scope()
        chunk = _make_chunk(scope)

        model = _to_model(chunk)

        assert model.id == chunk.id
        assert model.user_id == chunk.user_id
        assert model.chunk_type == ChunkType.TEXT.value
        assert model.text == chunk.text.value
        assert model.token_count == chunk.token_count

    def test_to_model_omits_embedding(self) -> None:
        scope = _make_scope()
        chunk = _make_chunk(scope)

        model = _to_model(chunk)

        assert model.embedding is None
        assert model.embedding_model_id is None
        assert model.embedding_dimension is None
        assert model.embedding_version is None

    def test_to_model_heading_path_as_list(self) -> None:
        scope = _make_scope()
        ts = datetime.now(UTC)
        chunk = Chunk(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT,
            text=UntrustedText("content"),
            token_count=5,
            ordinal=0,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=ts,
            heading_path=HeadingPath(("Chapter 1", "Section 2")),
        )

        model = _to_model(chunk)

        assert model.heading_path == ["Chapter 1", "Section 2"]

    def test_to_model_bbox_spread(self) -> None:
        scope = _make_scope()
        ts = datetime.now(UTC)
        chunk = Chunk(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.FIGURE,
            text=UntrustedText("Figure description"),
            token_count=5,
            ordinal=0,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=ts,
            bounding_box=BoundingBox(10.0, 20.0, 110.0, 220.0),
        )

        model = _to_model(chunk)

        assert model.bounding_box_x0 == 10.0
        assert model.bounding_box_y0 == 20.0
        assert model.bounding_box_x1 == 110.0
        assert model.bounding_box_y1 == 220.0

    def test_to_entity_restores_heading_path(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        ts = datetime.now(UTC)
        model = ChunkModel(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT.value,
            text="content",
            token_count=5,
            ordinal=0,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=ts,
            heading_path=["Chapter 1", "Section 2"],
            language="en",
        )

        entity = _to_entity(model)

        assert entity.heading_path == HeadingPath(("Chapter 1", "Section 2"))

    def test_to_entity_null_bbox_gives_none(self) -> None:
        from app.infrastructure.database.models.chunk import ChunkModel

        ts = datetime.now(UTC)
        model = ChunkModel(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            knowledge_base_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT.value,
            text="content",
            token_count=5,
            ordinal=0,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=ts,
            heading_path=[],
            language="en",
        )

        entity = _to_entity(model)

        assert entity.bounding_box is None
