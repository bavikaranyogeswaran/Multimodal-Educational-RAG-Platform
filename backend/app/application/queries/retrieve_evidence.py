"""Use case: orchestrate the full retrieval pipeline for a student query.

Classify → rewrite → plan → expand → search concurrently → fuse → rerank → prune → select.
The result is a ranked, relabelled evidence sequence ready for the prompt.

How many passages come back is decided at the end, from the class the query was given
at the start — a direct factual question and a comparison need different amounts of
material, and a single number chosen by the caller is wrong for one of them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace

import structlog

from app.application.observability.timer import StageTimer
from app.domain.models.entities import ConversationTurn
from app.domain.ports.adapters import DenseRetriever, EmbeddingPort, KeywordRetriever, RerankerPort
from app.domain.retrieval.classifier import QueryClassifier
from app.domain.retrieval.entities import Evidence, RetrievalFilters, RetrievalPlan
from app.domain.retrieval.expander import QueryExpander
from app.domain.retrieval.fusion import RRFusion
from app.domain.retrieval.pruning import EvidencePruner
from app.domain.retrieval.rewriter import QueryRewriter
from app.domain.retrieval.selector import EvidenceSelector
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetrieveEvidenceQuery:
    scope: ScopeContext
    query: str
    filters: RetrievalFilters
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
        pruner: EvidencePruner,
        selector: EvidenceSelector,
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
        self._pruner = pruner
        self._selector = selector

    async def execute(self, query: RetrieveEvidenceQuery) -> Sequence[Evidence]:
        with StageTimer("classify") as _timer:
            query_class = self._classifier.classify(query.query)
        _log.info("retrieval_stage", stage="classify", elapsed_ms=_timer.elapsed_ms())

        with StageTimer("rewrite") as _timer:
            standalone, _ = await self._rewriter.rewrite(query.query, query.history)
        _log.info("retrieval_stage", stage="rewrite", elapsed_ms=_timer.elapsed_ms())

        with StageTimer("plan_expand") as _timer:
            plan = RetrievalPlan.for_query(query_class, filters=query.filters)
            expanded = await self._expander.expand(standalone, plan)
        _log.info(
            "retrieval_stage",
            stage="plan_expand",
            elapsed_ms=_timer.elapsed_ms(),
            queries=len(expanded),
        )

        with StageTimer("embed") as _timer:
            embeddings = await asyncio.gather(*[self._embedder.embed_query(q) for q in expanded])
        _log.info(
            "retrieval_stage",
            stage="embed",
            elapsed_ms=_timer.elapsed_ms(),
            count=len(embeddings),
        )

        with StageTimer("search") as _timer:
            search_tasks = []
            for q, emb in zip(expanded, embeddings, strict=True):
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
        _log.info(
            "retrieval_stage",
            stage="search",
            elapsed_ms=_timer.elapsed_ms(),
            searchers=len(search_tasks),
        )

        with StageTimer("fuse") as _timer:
            fused = self._fuser.fuse(*all_results)[: self._candidate_pool_size]
            candidates = fused[: self._max_rerank_candidates]
        _log.info(
            "retrieval_stage",
            stage="fuse",
            elapsed_ms=_timer.elapsed_ms(),
            candidates=len(candidates),
        )

        if not candidates:
            return []

        with StageTimer("rerank") as _timer:
            texts = [c.chunk.text.value for c in candidates]
            scores = await self._reranker.rerank(standalone, texts)
            scored = sorted(
                zip(candidates, scores, strict=True), key=lambda x: x[1], reverse=True
            )
            ranked = [replace(e, rerank_score=s) for e, s in scored]
        _log.info(
            "retrieval_stage",
            stage="rerank",
            elapsed_ms=_timer.elapsed_ms(),
            results=len(ranked),
        )

        # Repetition first, then the count. Choosing five and then discovering three
        # were the same passage would leave two, having spent the budget on the copies.
        with StageTimer("prune") as _timer:
            distinct = self._pruner.prune(ranked, query_class=query_class)
        _log.info(
            "retrieval_stage",
            stage="prune",
            elapsed_ms=_timer.elapsed_ms(),
            before=len(ranked),
            after=len(distinct),
        )

        # How many of these reach the model is a question about the question, not a
        # number the caller supplies.
        with StageTimer("select") as _timer:
            selected = self._selector.select(distinct, query_class=query_class)
        _log.info(
            "retrieval_stage",
            stage="select",
            elapsed_ms=_timer.elapsed_ms(),
            query_class=query_class.value,
            considered=len(distinct),
            selected=len(selected),
        )
        return selected
