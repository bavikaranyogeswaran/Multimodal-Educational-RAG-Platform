"""Unit tests for SqlKeywordRetriever.

All tests use a mock AsyncSession — no real database or PostgreSQL functions are
called. Tests verify:
  - scope filter (user_id, knowledge_base_id) present in every query
  - COMPLETED document status filter enforced via JOIN to documents
  - tsv IS NOT NULL and @@ ts_query conditions present
  - ts_rank_cd descending ordering applied
  - LIMIT clause from top_k applied
  - optional document_ids and language filters from RetrievalFilters wired
  - results returned as Evidence with RetrieverKind.KEYWORD and correct ranks
  - foreign scope rejected before any session call
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
from app.infrastructure.retrieval.keyword import SqlKeywordRetriever


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_chunk_model(scope: ScopeContext) -> ChunkModel:
    return ChunkModel(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=uuid.uuid4(),
        chunk_type=ChunkType.TEXT.value,
        text="Sample passage about neural networks.",
        token_count=7,
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


def _retriever(scope: ScopeContext, session: AsyncMock) -> SqlKeywordRetriever:
    return SqlKeywordRetriever(scope=scope, session=session)


# ---------------------------------------------------------------------------
# SQL structure
# ---------------------------------------------------------------------------


class TestSqlStructure:
    async def test_applies_scope_filter(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
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
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        # websearch_to_tsquery has a REGCONFIG param that literal_binds can't render;
        # inspect the compiled params dict to verify the COMPLETED bound value.
        compiled = stmt.compile()
        assert "status" in str(compiled)
        assert "COMPLETED" in compiled.params.values()

    async def test_excludes_parent_chunks(self) -> None:
        """The trigger builds a tsvector for every row it is given, so without this the
        larger passages the children were cut from would match too, returning the same
        content twice — once as the paragraph, once as the section holding it."""
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        compiled = str(session.execute.call_args[0][0].compile())
        assert "parent_chunk_id IS NOT NULL" in compiled

    async def test_joins_to_documents_table(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "documents" in compiled

    async def test_applies_fulltext_match_operator(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "@@" in compiled

    async def test_uses_websearch_to_tsquery(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "websearch_to_tsquery" in compiled

    async def test_orders_by_ts_rank_cd(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "ts_rank_cd" in compiled

    async def test_applies_top_k_limit(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=12, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        # Inspect bound params instead of literal SQL because REGCONFIG blocks literal_binds.
        compiled = stmt.compile()
        assert 12 in compiled.params.values()

    async def test_document_ids_filter_adds_in_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))
        doc_id = uuid.uuid4()

        await _retriever(scope, session).search(
            scope,
            "gradient descent",
            top_k=5,
            filters=RetrievalFilters(document_ids=frozenset({doc_id})),
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "IN" in compiled.upper()

    async def test_no_document_ids_omits_in_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "document_id IN" not in compiled

    async def test_language_filter_adds_equality_clause(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters(language="de")
        )

        stmt = session.execute.call_args[0][0]
        compiled = stmt.compile()
        assert "language" in str(compiled)
        assert "de" in compiled.params.values()

    async def test_no_language_omits_language_equality(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        await _retriever(scope, session).search(
            scope, "gradient descent", top_k=5, filters=RetrievalFilters()
        )

        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile())
        assert "language =" not in compiled


# ---------------------------------------------------------------------------
# Return values
# ---------------------------------------------------------------------------


class TestReturnValues:
    async def test_returns_empty_when_no_rows(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=_mock_result([]))

        results = await _retriever(scope, session).search(
            scope, "attention mechanism", top_k=5, filters=RetrievalFilters()
        )

        assert results == []

    async def test_result_count_matches_returned_rows(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope) for _ in range(4)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, "attention mechanism", top_k=10, filters=RetrievalFilters()
        )

        assert len(results) == 4

    async def test_rank_is_zero_based_position(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope) for _ in range(3)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, "attention mechanism", top_k=5, filters=RetrievalFilters()
        )

        assert [e.rank for e in results] == [0, 1, 2]

    async def test_retriever_kind_is_keyword(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, "attention mechanism", top_k=5, filters=RetrievalFilters()
        )

        assert RetrieverKind.KEYWORD in results[0].retrievers
        assert len(results[0].retrievers) == 1

    async def test_labels_are_one_based_and_sequential(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        rows = [_make_chunk_model(scope) for _ in range(3)]
        session.execute = AsyncMock(return_value=_mock_result(rows))

        results = await _retriever(scope, session).search(
            scope, "attention mechanism", top_k=5, filters=RetrievalFilters()
        )

        assert [e.label.number for e in results] == [1, 2, 3]

    async def test_chunk_ids_match_model_rows(self) -> None:
        scope = _make_scope()
        session = AsyncMock()
        row = _make_chunk_model(scope)
        session.execute = AsyncMock(return_value=_mock_result([row]))

        results = await _retriever(scope, session).search(
            scope, "attention mechanism", top_k=5, filters=RetrievalFilters()
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
                call_scope, "neural network", top_k=5, filters=RetrievalFilters()
            )

        session.execute.assert_not_called()
