"""Unit tests for SqlDenseRetriever.

All tests use a mock AsyncSession — no real database or pgvector calls are made.
Tests verify:
  - scope filter (user_id, knowledge_base_id) appears in every query
  - COMPLETED document status filter enforced via JOIN to documents
  - embedding IS NOT NULL filter excludes un-embedded chunks
  - cosine_distance ordering (<=> operator) is applied
  - LIMIT clause is applied from top_k
  - document_ids and language filters from RetrievalFilters are wired
  - results are returned as Evidence with RetrieverKind.DENSE and correct ranks
  - foreign scope is rejected before any session call
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enums import ChunkType, RetrieverKind
from app.domain.errors import ScopeViolationError
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.chunk import ChunkModel
from app.infrastructure.retrieval.dense import SqlDenseRetriever

_QUERY_VECTOR = [0.1] * 384


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_chunk_model(scope: ScopeContext) -> ChunkModel:
    return ChunkModel(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=uuid.uuid4(),
        chunk_type=ChunkType.TEXT.value,
        text="Sample passage text.",
        token_count=5,
        ordinal=0,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=datetime.now(UTC),
        heading_path=[],
        language="en",
    )


def _mock_result(rows: list[object]) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _retriever(scope: ScopeContext, session: AsyncMock) -> SqlDenseRetriever:
    return SqlDenseRetriever(scope=scope, session=session)


# ---------------------------------------------------------------------------
# SQL structure — verify the statement before it reaches the database
# ---------------------------------------------------------------------------


class TestSqlStructure:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "user_id" in compiled
        assert "knowledge_base_id" in compiled

    async def test_enforces_completed_document_status(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "COMPLETED" in compiled
        assert "status" in compiled

    async def test_joins_to_documents_table(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "documents" in compiled

    async def test_excludes_un_embedded_chunks(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "embedding" in compiled
        assert "NULL" in compiled.upper()

    async def test_pins_the_active_index_version(self) -> None:
        """Vectors from two embedding models are not comparable, and a rebuild is
        exactly when both are in the table. Distances across them are still numbers,
        so a search that mixed them would rank badly and report nothing wrong."""
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        compiled = str(session.execute.call_args[0][0].compile())
        assert "index_version" in compiled
        assert "active_index_version" in compiled

    async def test_reads_the_active_version_from_this_knowledge_base(self) -> None:
        """Taken from the row rather than passed in, so a caller cannot leave it out."""
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        compiled = session.execute.call_args[0][0].compile()
        assert "knowledge_bases" in str(compiled)
        assert scope.knowledge_base_id in compiled.params.values()

    async def test_excludes_parent_chunks(self) -> None:
        """Only the small chunks are searched. Their parents are loaded around a hit,
        and matching those as well would return the same content twice — once as the
        paragraph, once as the section holding it — for two slots in one ranking."""
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        compiled = str(session.execute.call_args[0][0].compile())
        assert "parent_chunk_id IS NOT NULL" in compiled

    async def test_applies_cosine_distance_ordering(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "<=>" in compiled

    async def test_applies_top_k_limit(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=7, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "7" in compiled

    async def test_document_ids_filter_adds_in_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))
        doc_id = uuid.uuid4()

        await _retriever(scope, session).search(
            scope,
            _QUERY_VECTOR,
            top_k=5,
            filters=RetrievalFilters(document_ids=frozenset({doc_id})),
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "document_id" in compiled
        assert "IN" in compiled.upper()

    async def test_no_document_ids_filter_omits_in_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        # document_id appears in the SELECT list; the IN filter must not be added
        assert "document_id IN" not in compiled

    async def test_language_filter_adds_equality_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope,
            _QUERY_VECTOR,
            top_k=5,
            filters=RetrievalFilters(language="fr"),
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "language" in compiled
        assert "fr" in compiled

    async def test_no_language_filter_omits_language_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        # language appears in the SELECT list; the equality filter must not be added
        assert "language =" not in compiled


# ---------------------------------------------------------------------------
# Return value contract
# ---------------------------------------------------------------------------


class TestReturnValues:
    async def test_returns_empty_when_no_rows(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        results = await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        assert results == []

    async def test_result_count_matches_returned_rows(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope) for _ in range(3)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        assert len(results) == 3

    async def test_rank_is_zero_based_position(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope) for _ in range(3)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        assert [e.rank for e in results] == [0, 1, 2]

    async def test_retriever_kind_is_dense(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        assert RetrieverKind.DENSE in results[0].retrievers
        assert len(results[0].retrievers) == 1

    async def test_labels_are_one_based_and_sequential(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope) for _ in range(3)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        assert [e.label.number for e in results] == [1, 2, 3]

    async def test_chunk_ids_match_model_rows(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        row = _make_chunk_model(scope)
        session.execute = AsyncMock(return_value=_mock_result([row]))

        results = await _retriever(scope, session).search(
            scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
        )

        assert results[0].chunk.id == row.id


# ---------------------------------------------------------------------------
# Scope guard
# ---------------------------------------------------------------------------


class TestScopeGuard:
    async def test_rejects_foreign_scope(self) -> None:
        bound_scope = _make_scope()
        call_scope = _make_scope()
        session = AsyncMock()

        retriever = _retriever(bound_scope, session)

        with pytest.raises(ScopeViolationError):
            await retriever.search(
                call_scope, _QUERY_VECTOR, top_k=5, filters=RetrievalFilters()
            )

        session.execute.assert_not_called()
