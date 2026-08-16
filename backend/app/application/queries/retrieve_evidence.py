"""Use case: orchestrate the full retrieval pipeline for a student query.

Classify → rewrite → plan → expand → search concurrently → fuse → rerank.
The result is a ranked, relabelled evidence sequence ready for the prompt.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.domain.models.entities import ConversationTurn
from app.domain.ports.adapters import DenseRetriever, EmbeddingPort, KeywordRetriever, RerankerPort
from app.domain.retrieval.classifier import QueryClassifier
from app.domain.retrieval.entities import Evidence, EvidenceLabel, RetrievalFilters, RetrievalPlan
from app.domain.retrieval.expander import QueryExpander
from app.domain.retrieval.fusion import RRFusion
from app.domain.retrieval.rewriter import QueryRewriter
from app.domain.scope import ScopeContext


@dataclass(frozen=True)
class RetrieveEvidenceQuery:
    scope: ScopeContext
    query: str
    filters: RetrievalFilters
    top_k: int
    history: tuple[ConversationTurn, ...] = ()


class RetrievalOrchestrator:
    """Coordinate the full retrieval pipeline for one query."""

    def __init__(
        self,
        *,
        classifier: QueryClassifier,
        rewriter: QueryRewriter,
        expander: QueryExpander,
        embedder: EmbeddingPort,
        dense_retriever: DenseRetriever,
        keyword_retriever: KeywordRetriever,
        fuser: RRFusion,
        reranker: RerankerPort,
        dense_top_k: int,
        keyword_top_k: int,
        candidate_pool_size: int,
        max_rerank_candidates: int,
        relative_score_margin: float,
    ) -> None:
        self._classifier = classifier
        self._rewriter = rewriter
        self._expander = expander
        self._embedder = embedder
        self._dense_retriever = dense_retriever
        self._keyword_retriever = keyword_retriever
        self._fuser = fuser
        self._reranker = reranker
        self._dense_top_k = dense_top_k
        self._keyword_top_k = keyword_top_k
        self._candidate_pool_size = candidate_pool_size
        self._max_rerank_candidates = max_rerank_candidates
        self._relative_score_margin = relative_score_margin

    async def execute(self, query: RetrieveEvidenceQuery) -> Sequence[Evidence]:
        query_class = self._classifier.classify(query.query)
        standalone, _ = await self._rewriter.rewrite(query.query, query.history)
        plan = RetrievalPlan.for_query(query_class, filters=query.filters)
        expanded = await self._expander.expand(standalone, plan)

        embeddings = await asyncio.gather(*[self._embedder.embed_query(q) for q in expanded])

        search_tasks = []
        for q, emb in zip(expanded, embeddings):
            search_tasks.append(
                self._dense_retriever.search(
                    query.scope, emb, top_k=self._dense_top_k, filters=plan.filters
                )
            )
            search_tasks.append(
                self._keyword_retriever.search(
                    query.scope, q, top_k=self._keyword_top_k, filters=plan.filters
                )
            )
        all_results = await asyncio.gather(*search_tasks)

        fused = self._fuser.fuse(*all_results)[: self._candidate_pool_size]
        candidates = fused[: self._max_rerank_candidates]
        if not candidates:
            return []

        texts = [c.chunk.text.value for c in candidates]
        scores = await self._reranker.rerank(standalone, texts)

        scored = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        top_score = scored[0][1]
        threshold = top_score - abs(top_score) * self._relative_score_margin
        filtered = [(e, s) for e, s in scored if s >= threshold]

        return [
            replace(e, label=EvidenceLabel(i + 1), rank=i, rerank_score=s)
            for i, (e, s) in enumerate(filtered[: query.top_k])
        ]
