"""FastAPI dependency: assemble RetrievalOrchestrator for route handlers.

SqlDenseRetriever and SqlKeywordRetriever are per-request (they hold a scoped DB
session). Pure computation collaborators (classifier, rewriter, expander, fuser)
are lightweight and also constructed per-request. The embedder and reranker
(which hold ML model weights) are singletons pulled from the container.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.container import get_container
from app.api.dependencies.scope import get_kb_scope
from app.application.queries.retrieve_evidence import RetrievalOrchestrator
from app.configuration.container import Container
from app.configuration.settings import get_settings
from app.domain.retrieval.classifier import QueryClassifier
from app.domain.retrieval.compression import EvidenceCompressor
from app.domain.retrieval.expander import QueryExpander
from app.domain.retrieval.expansion import ExpansionRules
from app.domain.retrieval.fusion import RRFusion
from app.domain.retrieval.pruning import EvidencePruner
from app.domain.retrieval.rewriter import QueryRewriter
from app.domain.retrieval.selector import EvidenceSelector
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.database.session import get_session
from app.infrastructure.retrieval.dense import SqlDenseRetriever
from app.infrastructure.retrieval.keyword import SqlKeywordRetriever


async def get_retrieval_orchestrator(
    scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    session: Annotated[AsyncSession, Depends(get_session)],
    container: Annotated[Container, Depends(get_container)],
) -> RetrievalOrchestrator:
    settings = get_settings()
    return RetrievalOrchestrator(
        classifier=QueryClassifier(),
        rewriter=QueryRewriter(gateway=container.model_gateway),
        expander=QueryExpander(gateway=container.model_gateway),
        embedder=container.embedder,
        dense_retriever=SqlDenseRetriever(scope=scope, session=session),
        keyword_retriever=SqlKeywordRetriever(scope=scope, session=session),
        fuser=RRFusion(),
        reranker=container.reranker,
        dense_top_k=settings.retrieval.dense_top_k,
        keyword_top_k=settings.retrieval.keyword_top_k,
        candidate_pool_size=settings.retrieval.candidate_pool_size,
        max_rerank_candidates=settings.reranker.max_candidates,
        pruner=EvidencePruner(
            overlap_threshold=settings.evidence.duplicate_overlap_threshold,
            max_children_per_parent=settings.evidence.max_children_per_parent,
            max_chunks_per_page=settings.evidence.max_chunks_per_page,
            max_chunks_per_document=settings.evidence.max_chunks_per_document,
        ),
        expansion_rules=ExpansionRules(),
        chunks=SqlChunkRepository(scope, session),
        selector=EvidenceSelector(
            container.token_counter.count,
            min_items=settings.evidence.min_items,
            max_items=settings.evidence.max_items,
            relative_score_margin=settings.evidence.relative_score_margin,
            token_budget=settings.evidence.context_token_budget,
        ),
        compressor=EvidenceCompressor(
            container.token_counter.count,
            token_budget=settings.evidence.context_token_budget,
            generative_enabled=settings.evidence.generative_compression_enabled,
        ),
    )
