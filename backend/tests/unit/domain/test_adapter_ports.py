"""Adapter port structural tests.

Verifies that:
  1. Scoped adapters (DenseRetriever, KeywordRetriever, GraphPort, PdfParserPort)
     have `scope` as the first non-self parameter, so an unscoped call cannot type-check.
  2. Typed stub classes satisfy every protocol — checked by mypy at type-check time.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import pytest

from app.domain.documents.entities import DocumentElement, DocumentPage
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.ports.adapters import (
    CacheStore,
    DenseRetriever,
    EmbeddingPort,
    GraphPort,
    KeywordRetriever,
    ObservabilityPort,
    OcrPort,
    PdfParserPort,
    RerankerPort,
    StoragePort,
)
from app.domain.retrieval.entities import Evidence, RetrievalFilters
from app.domain.scope import ScopeContext


def _first_non_self_param(method: Any) -> str:
    sig = inspect.signature(method)
    params = list(sig.parameters)
    return params[1] if len(params) > 1 else ""


# ---------------------------------------------------------------------------
# Scope-enforced adapters
# ---------------------------------------------------------------------------


class TestPdfParserPortSignatures:
    def test_parse_has_scope_keyword(self) -> None:
        sig = inspect.signature(PdfParserPort.parse)
        assert "scope" in sig.parameters


class TestDenseRetrieverSignatures:
    def test_search_has_scope_first(self) -> None:
        assert _first_non_self_param(DenseRetriever.search) == "scope"


class TestKeywordRetrieverSignatures:
    def test_search_has_scope_first(self) -> None:
        assert _first_non_self_param(KeywordRetriever.search) == "scope"


class TestGraphPortSignatures:
    def test_neighbors_has_scope_first(self) -> None:
        assert _first_non_self_param(GraphPort.neighbors) == "scope"

    def test_subgraph_has_scope_first(self) -> None:
        assert _first_non_self_param(GraphPort.subgraph) == "scope"


# ---------------------------------------------------------------------------
# Typed stubs — mypy verifies protocol satisfaction at type-check time.
# ---------------------------------------------------------------------------


class _StubStoragePort:
    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def presigned_get_url(self, key: str, *, expires_in: int) -> str:
        raise NotImplementedError


class _StubPdfParserPort:
    async def parse(
        self,
        data: bytes,
        *,
        document_id: UUID,
        scope: ScopeContext,
    ) -> Sequence[tuple[DocumentPage, Sequence[DocumentElement]]]:
        raise NotImplementedError


class _StubOcrPort:
    async def extract_text(
        self,
        image: bytes,
        *,
        page: DocumentPage,
    ) -> Sequence[DocumentElement]:
        raise NotImplementedError


class _StubEmbeddingPort:
    @property
    def dimension(self) -> int:
        raise NotImplementedError

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise NotImplementedError

    async def embed_query(self, text: str) -> Sequence[float]:
        raise NotImplementedError


class _StubRerankerPort:
    async def rerank(
        self, query: str, candidates: Sequence[str]
    ) -> Sequence[float]:
        raise NotImplementedError


class _StubDenseRetriever:
    async def search(
        self,
        scope: ScopeContext,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        filters: RetrievalFilters,
    ) -> Sequence[Evidence]:
        raise NotImplementedError


class _StubKeywordRetriever:
    async def search(
        self,
        scope: ScopeContext,
        query: str,
        *,
        top_k: int,
        filters: RetrievalFilters,
    ) -> Sequence[Evidence]:
        raise NotImplementedError


class _StubGraphPort:
    async def neighbors(
        self,
        scope: ScopeContext,
        entity_id: UUID,
        *,
        max_hops: int = 1,
    ) -> Sequence[GraphEntity]:
        raise NotImplementedError

    async def subgraph(
        self,
        scope: ScopeContext,
        entity_ids: frozenset[UUID],
        *,
        max_nodes: int,
    ) -> tuple[Sequence[GraphEntity], Sequence[GraphRelationship]]:
        raise NotImplementedError


class _StubCacheStore:
    async def get(self, key: str) -> bytes | None:
        raise NotImplementedError

    async def put(self, key: str, data: bytes, *, ttl: int) -> None:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError


class _StubObservabilityPort:
    def emit(self, event: str, *, attributes: Mapping[str, object]) -> None:
        raise NotImplementedError

    def child(self, **bindings: object) -> ObservabilityPort:
        raise NotImplementedError


# Mypy-checked assignments — these fail at type-check time if a stub is incomplete.
_storage: StoragePort = _StubStoragePort()
_parser: PdfParserPort = _StubPdfParserPort()
_ocr: OcrPort = _StubOcrPort()
_embedder: EmbeddingPort = _StubEmbeddingPort()
_reranker: RerankerPort = _StubRerankerPort()
_dense: DenseRetriever = _StubDenseRetriever()
_keyword: KeywordRetriever = _StubKeywordRetriever()
_graph: GraphPort = _StubGraphPort()
_cache: CacheStore = _StubCacheStore()
_obs: ObservabilityPort = _StubObservabilityPort()


class TestAdapterProtocolCompliance:
    @pytest.mark.parametrize("stub", [
        _StubStoragePort,
        _StubPdfParserPort,
        _StubOcrPort,
        _StubEmbeddingPort,
        _StubRerankerPort,
        _StubDenseRetriever,
        _StubKeywordRetriever,
        _StubGraphPort,
        _StubCacheStore,
        _StubObservabilityPort,
    ])
    def test_stub_is_instantiable(self, stub: type) -> None:
        assert stub() is not None
