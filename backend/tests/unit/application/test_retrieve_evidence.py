"""Unit tests for RetrieveEvidenceUseCase.

All dependencies are mocked — no real embedder, database, or retriever is involved.
Tests verify the delegation contract: the use case embeds the query text, passes the
resulting vector plus scope/top_k/filters to the dense retriever, and returns whatever
the retriever provides unchanged.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from app.application.queries.retrieve_evidence import (
    RetrieveEvidenceQuery,
    RetrieveEvidenceUseCase,
)
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext

_VECTOR = [0.1] * 384


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _query(
    *,
    scope: ScopeContext | None = None,
    text: str = "what is photosynthesis",
    top_k: int = 10,
    filters: RetrievalFilters | None = None,
) -> RetrieveEvidenceQuery:
    return RetrieveEvidenceQuery(
        scope=scope if scope is not None else _scope(),
        query=text,
        top_k=top_k,
        filters=filters if filters is not None else RetrievalFilters(),
    )


def _make(
    *,
    vector: list[float] | None = None,
    results: list | None = None,
) -> tuple[RetrieveEvidenceUseCase, AsyncMock, AsyncMock]:
    embedder: AsyncMock = AsyncMock()
    embedder.embed_query.return_value = vector if vector is not None else _VECTOR
    retriever: AsyncMock = AsyncMock()
    retriever.search.return_value = results if results is not None else []
    use_case = RetrieveEvidenceUseCase(embedder=embedder, dense_retriever=retriever)
    return use_case, embedder, retriever


class TestRetrieveEvidenceUseCase:
    async def test_embeds_the_query_string(self) -> None:
        use_case, embedder, _ = _make()
        await use_case.execute(_query(text="explain osmosis"))
        embedder.embed_query.assert_called_once_with("explain osmosis")

    async def test_passes_embedding_to_retriever(self) -> None:
        vector = [0.9] * 384
        use_case, _, retriever = _make(vector=vector)
        await use_case.execute(_query())
        call_vector = retriever.search.call_args.args[1]
        assert list(call_vector) == vector

    async def test_passes_scope_to_retriever(self) -> None:
        scope = _scope()
        use_case, _, retriever = _make()
        await use_case.execute(_query(scope=scope))
        assert retriever.search.call_args.args[0] is scope

    async def test_passes_top_k_to_retriever(self) -> None:
        use_case, _, retriever = _make()
        await use_case.execute(_query(top_k=15))
        assert retriever.search.call_args.kwargs["top_k"] == 15

    async def test_passes_filters_to_retriever(self) -> None:
        doc_id = uuid.uuid4()
        filters = RetrievalFilters(document_ids=frozenset({doc_id}), language="fr")
        use_case, _, retriever = _make()
        await use_case.execute(_query(filters=filters))
        assert retriever.search.call_args.kwargs["filters"] == filters

    async def test_returns_retriever_results(self) -> None:
        sentinel = [object(), object()]
        use_case, _, _ = _make(results=sentinel)
        result = await use_case.execute(_query())
        assert list(result) == sentinel

    async def test_returns_empty_sequence_when_no_results(self) -> None:
        use_case, _, _ = _make(results=[])
        result = await use_case.execute(_query())
        assert len(result) == 0
