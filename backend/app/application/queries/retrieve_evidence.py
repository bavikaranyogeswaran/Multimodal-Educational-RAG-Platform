"""Use case: orchestrate the full retrieval pipeline for a student query.

Classify → rewrite → plan → expand queries → search → fuse → rerank → prune → expand
parents → select → compress.
The result is a ranked, relabelled evidence sequence ready for the prompt.

How many passages come back is decided at the end, from the class the query was given
at the start — a direct factual question and a comparison need different amounts of
material, and a single number chosen by the caller is wrong for one of them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

import structlog

from app.application.observability.timer import StageTimer
from app.domain.models.entities import ConversationTurn
from app.domain.ports.adapters import DenseRetriever, EmbeddingPort, KeywordRetriever, RerankerPort
from app.domain.ports.repositories import ChunkRepository
from app.domain.retrieval.classifier import QueryClassifier
from app.domain.retrieval.compression import EvidenceCompressor
from app.domain.retrieval.entities import Evidence, RetrievalFilters, RetrievalPlan
from app.domain.retrieval.expander import QueryExpander
from app.domain.retrieval.expansion import ExpansionReason, ExpansionRules
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


@dataclass(frozen=True)
class RetrievalResult:
    evidence: Sequence[Evidence]
    standalone_query: str
    was_rewritten: bool


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
        expansion_rules: ExpansionRules,
        chunks: ChunkRepository,
        selector: EvidenceSelector,
        compressor: EvidenceCompressor,
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
        self._expansion_rules = expansion_rules
        self._chunks = chunks
        self._selector = selector
        self._compressor = compressor

    async def execute(self, query: RetrieveEvidenceQuery) -> RetrievalResult:
        with StageTimer("classify") as _timer:
            query_class = self._classifier.classify(query.query)
        _log.info("retrieval_stage", stage="classify", elapsed_ms=_timer.elapsed_ms())

        with StageTimer("rewrite") as _timer:
            standalone, was_rewritten = await self._rewriter.rewrite(query.query, query.history)
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
            return RetrievalResult(evidence=[], standalone_query=standalone, was_rewritten=was_rewritten)

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

        # Before the count, because expansion changes how much each passage costs and
        # the budget is spent in the step after this one.
        with StageTimer("expand_parents") as _timer:
            complete = await self._expand_incomplete(query.scope, distinct)
        _log.info(
            "retrieval_stage",
            stage="expand_parents",
            elapsed_ms=_timer.elapsed_ms(),
            expanded=sum(1 for e in complete if e.parent_expanded),
        )

        # How many of these reach the model is a question about the question, not a
        # number the caller supplies.
        with StageTimer("select") as _timer:
            selected = self._selector.select(complete, query_class=query_class)
        _log.info(
            "retrieval_stage",
            stage="select",
            elapsed_ms=_timer.elapsed_ms(),
            query_class=query_class.value,
            considered=len(complete),
            selected=len(selected),
        )
        # Last, on the passages actually being sent. Shortening something that was never
        # going to be sent is wasted, and shortening before the count would let a
        # marginal passage in on the strength of a cut that discards its relevant half.
        with StageTimer("compress") as _timer:
            fitted = self._compressor.compress(selected, query=standalone)
        _log.info(
            "retrieval_stage",
            stage="compress",
            elapsed_ms=_timer.elapsed_ms(),
            compressed=sum(1 for e in fitted if e.compressed),
        )
        return RetrievalResult(evidence=fitted, standalone_query=standalone, was_rewritten=was_rewritten)

    # -----------------------------------------------------------------------

    async def _expand_incomplete(
        self, scope: ScopeContext, evidence: Sequence[Evidence]
    ) -> list[Evidence]:
        """Replace the fragments that cannot be read alone with the sections holding them.

        One query for the whole list rather than one per passage: this runs while somebody
        waits for an answer, and a round trip per fragment would put the database inside
        that wait as many times as there are passages.

        Where two fragments come from the same section, only the first is expanded. The
        second would become a copy of the first, which is the repetition the step before
        this one exists to remove, arriving after it has finished looking.
        """
        wanted: dict[UUID, ExpansionReason] = {}
        for item in evidence:
            reason = self._expansion_rules.reason_to_expand(item.chunk)
            if reason is not None and item.chunk.parent_chunk_id is not None:
                wanted.setdefault(item.chunk.parent_chunk_id, reason)

        if not wanted:
            return list(evidence)

        parents = {
            parent.id: parent
            for parent in await self._chunks.get_many(scope, list(wanted))
        }

        expanded: list[Evidence] = []
        used: set[UUID] = set()
        for item in evidence:
            parent_id = item.chunk.parent_chunk_id
            parent = parents.get(parent_id) if parent_id is not None else None
            # A parent that has been deleted, or that this scope cannot see, leaves the
            # fragment exactly as retrieval found it. Incomplete is better than absent.
            if parent is None or parent_id in used or parent_id not in wanted:
                expanded.append(item)
                continue
            used.add(parent_id)
            expanded.append(replace(item, chunk=parent, parent_expanded=True))
        return expanded
