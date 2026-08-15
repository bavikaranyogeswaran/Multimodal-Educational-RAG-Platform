"""Use case: embed a query and retrieve the most relevant evidence chunks.

The use case sits between the API layer and the retrieval infrastructure. It
owns the decision to embed the query text before searching; everything else
(scope enforcement, cosine distance, limit) belongs to the retriever.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.ports.adapters import DenseRetriever, EmbeddingPort
from app.domain.retrieval.entities import Evidence, RetrievalFilters
from app.domain.scope import ScopeContext


@dataclass(frozen=True)
class RetrieveEvidenceQuery:
    scope: ScopeContext
    query: str
    filters: RetrievalFilters
    top_k: int


class RetrieveEvidenceUseCase:
    """Embed a natural-language query and delegate to the dense retriever."""

    def __init__(
        self,
        embedder: EmbeddingPort,
        dense_retriever: DenseRetriever,
    ) -> None:
        self._embedder = embedder
        self._dense_retriever = dense_retriever

    async def execute(self, query: RetrieveEvidenceQuery) -> Sequence[Evidence]:
        vector = await self._embedder.embed_query(query.query)
        return await self._dense_retriever.search(
            query.scope,
            vector,
            top_k=query.top_k,
            filters=query.filters,
        )
