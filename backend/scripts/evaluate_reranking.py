"""Measure what the cross-encoder reranker contributes over the RRF fusion order.

Two orchestrators run for every gold question:
  bypass   — identity reranker: RRF order preserved, no cross-encoder scoring
  reranked — real reranker, exactly as the API wires it

Delta (reranked − bypass) is the reranker's contribution. A positive delta means
the cross-encoder pushed relevant passages higher than pure fusion did.

Three metrics are compared at each position:
  page_recall@K   — did retrieval surface all gold pages?
  MRR             — how high does the first relevant passage rank?
  NDCG@K          — is the full ranking ordered well?

The 'r1' column shows the 1-indexed rank of the first relevant passage before
and after reranking, making score changes concrete (e.g. "3→1").

Usage:
    uv run python scripts/evaluate_reranking.py <knowledge-base-id> [gold-set.json]
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from scripts._eval_store import save_run

from app.api.dependencies.retrieval import build_retrieval_orchestrator
from app.application.queries.retrieve_evidence import (
    RetrievalOrchestrator,
    RetrieveEvidenceQuery,
)
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.evaluation.entities import GoldPair
from app.domain.evaluation.metrics import RetrievalScores, score
from app.domain.retrieval.compression import EvidenceCompressor
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.retrieval.expander import QueryExpander
from app.domain.retrieval.expansion import ExpansionRules
from app.domain.retrieval.fusion import RRFusion
from app.domain.retrieval.pruning import EvidencePruner
from app.domain.retrieval.rewriter import QueryRewriter
from app.domain.retrieval.selector import EvidenceSelector
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.chunk import SqlChunkRepository
from app.infrastructure.evaluation.gold_set_file import load_gold_set
from app.infrastructure.observability.structlog_setup import configure_structlog
from app.infrastructure.retrieval.dense import SqlDenseRetriever
from app.infrastructure.retrieval.keyword import SqlKeywordRetriever

_DEFAULT_GOLD = (
    Path(__file__).parent.parent / "evaluation" / "gold" / "data-science-in-the-cloud.json"
)

_K = 10


class _IdentityReranker:
    """Passthrough reranker that preserves the RRF fusion order.

    Returns descending scores so the pipeline's sort-by-score-descending step
    leaves candidates in the exact order fusion produced them.
    """

    async def rerank(self, query: str, candidates: Sequence[str]) -> Sequence[float]:
        return [float(len(candidates) - i) for i in range(len(candidates))]


def _build_bypass_orchestrator(container, settings, scope: ScopeContext, session) -> RetrievalOrchestrator:
    """Mirrors build_retrieval_orchestrator exactly, substituting the identity reranker.

    Both variables are duck-typed here so the function stays dependency-free. The only
    difference from the real factory is reranker=_IdentityReranker().
    """
    return RetrievalOrchestrator(
        classifier=container.query_classifier,
        rewriter=QueryRewriter(gateway=container.model_gateway),
        expander=QueryExpander(gateway=container.model_gateway),
        embedder=container.embedder,
        dense_retriever=SqlDenseRetriever(scope=scope, session=session),  # type: ignore[arg-type]
        keyword_retriever=SqlKeywordRetriever(scope=scope, session=session),  # type: ignore[arg-type]
        fuser=RRFusion(),
        reranker=_IdentityReranker(),  # type: ignore[arg-type]
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
        chunks=SqlChunkRepository(scope, session),  # type: ignore[arg-type]
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


def _first_relevant_rank(pages: list[list[int]], gold: frozenset[int]) -> int | None:
    """1-indexed rank of the first evidence item that touches a gold page, or None."""
    for i, page_list in enumerate(pages, start=1):
        if any(p in gold for p in page_list):
            return i
    return None


async def _run_one(
    orchestrator: RetrievalOrchestrator,
    scope: ScopeContext,
    pair: GoldPair,
) -> tuple[RetrievalScores | None, int | None]:
    result = await orchestrator.execute(
        RetrieveEvidenceQuery(scope=scope, query=pair.question, filters=RetrievalFilters())
    )
    evidence = list(result.evidence)
    pages = [list(range(item.chunk.page_start, item.chunk.page_end + 1)) for item in evidence]
    texts = [item.chunk.text.value for item in evidence]

    if pair.unanswerable:
        return None, None

    return (
        score(
            pages,
            pair.gold_pages,
            k=_K,
            retrieved_text=texts,
            must_contain=pair.must_contain,
        ),
        _first_relevant_rank(pages, pair.gold_pages),
    )


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _r1(rank: int | None) -> str:
    return str(rank) if rank is not None else "—"


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)

    kb_id = UUID(sys.argv[1])
    gold_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_GOLD
    gold = load_gold_set(gold_path)

    settings = get_settings()
    configure_structlog(settings)
    container = build_container(settings)

    async with container.session_factory() as session:
        user_id = (
            await session.execute(
                text("SELECT user_id FROM knowledge_bases WHERE id = :kb"),
                {"kb": kb_id},
            )
        ).scalar_one()

    scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)

    print(f"gold set : {gold_path.name}")
    print(f"source   : {gold.source}")
    print(f"pairs    : {len(gold.pairs)} ({len(gold.answerable)} answerable)")
    print(f"window   : top {_K}")
    print(f"reranker : {type(container.reranker).__name__}\n")

    col = 24
    header = (
        f"{'pair':<{col}}  "
        f"{'rec_b':>5} {'rr_b':>5} {'ndcg_b':>6}  "
        f"{'rec_r':>5} {'rr_r':>5} {'ndcg_r':>6}  "
        f"{'Δrec':>5} {'Δrr':>5} {'Δndcg':>5}  "
        f"{'r1_b':>4} {'r1_r':<4}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    b_scores: list[RetrievalScores] = []
    r_scores: list[RetrievalScores] = []
    rec_deltas: list[float] = []
    rr_deltas: list[float] = []
    ndcg_deltas: list[float] = []
    r1_lifts: list[int] = []

    async with container.session_factory() as session:
        bypass = _build_bypass_orchestrator(container, settings, scope, session)
        reranked = build_retrieval_orchestrator(container, settings, scope, session)

        for pair in gold.pairs:
            b_result, b_r1 = await _run_one(bypass, scope, pair)
            r_result, r_r1 = await _run_one(reranked, scope, pair)

            if b_result is None:
                # unanswerable — skip scoring, just note it
                print(f"{pair.id:<{col}}  {'unanswerable':>50}  {_r1(b_r1):>4} {_r1(r_r1):<4}")
                continue

            assert r_result is not None, "answerable pair returned None from reranked run"

            b_scores.append(b_result)
            r_scores.append(r_result)

            delta_rec = r_result.page_recall - b_result.page_recall
            delta_rr = r_result.reciprocal_rank - b_result.reciprocal_rank
            delta_ndcg = r_result.ndcg - b_result.ndcg

            rec_deltas.append(delta_rec)
            rr_deltas.append(delta_rr)
            ndcg_deltas.append(delta_ndcg)

            if b_r1 is not None and r_r1 is not None:
                r1_lifts.append(b_r1 - r_r1)

            print(
                f"{pair.id:<{col}}  "
                f"{b_result.page_recall:>5.2f} {b_result.reciprocal_rank:>5.2f} {b_result.ndcg:>6.3f}  "
                f"{r_result.page_recall:>5.2f} {r_result.reciprocal_rank:>5.2f} {r_result.ndcg:>6.3f}  "
                f"{delta_rec:>+5.2f} {delta_rr:>+5.2f} {delta_ndcg:>+5.3f}  "
                f"{_r1(b_r1):>4} {_r1(r_r1):<4}"
            )

    print(sep)
    print(
        f"{'MEAN':<{col}}  "
        f"{_mean([s.page_recall for s in b_scores]):>5.2f} "
        f"{_mean([s.reciprocal_rank for s in b_scores]):>5.2f} "
        f"{_mean([s.ndcg for s in b_scores]):>6.3f}  "
        f"{_mean([s.page_recall for s in r_scores]):>5.2f} "
        f"{_mean([s.reciprocal_rank for s in r_scores]):>5.2f} "
        f"{_mean([s.ndcg for s in r_scores]):>6.3f}  "
        f"{_mean(rec_deltas):>+5.2f} {_mean(rr_deltas):>+5.2f} {_mean(ndcg_deltas):>+5.3f}"
    )

    if r1_lifts:
        avg_lift = _mean([float(x) for x in r1_lifts])
        improved = sum(1 for x in r1_lifts if x > 0)
        unchanged = sum(1 for x in r1_lifts if x == 0)
        degraded = sum(1 for x in r1_lifts if x < 0)
        n = len(r1_lifts)
        print(
            f"\nrank-1 lift  : avg {avg_lift:+.1f} positions  "
            f"({improved}/{n} improved, {unchanged}/{n} unchanged, {degraded}/{n} degraded)"
        )

    print(
        f"\nreranker adds: NDCG {_mean(ndcg_deltas):+.3f}  MRR {_mean(rr_deltas):+.3f}  "
        f"recall {_mean(rec_deltas):+.3f}  over RRF-only order"
    )

    result_path = save_run(
        "reranking",
        kb_id,
        gold.source,
        {
            "bypass_page_recall": _mean([s.page_recall for s in b_scores]),
            "bypass_mrr": _mean([s.reciprocal_rank for s in b_scores]),
            "bypass_ndcg": _mean([s.ndcg for s in b_scores]),
            "reranked_page_recall": _mean([s.page_recall for s in r_scores]),
            "reranked_mrr": _mean([s.reciprocal_rank for s in r_scores]),
            "reranked_ndcg": _mean([s.ndcg for s in r_scores]),
            "delta_recall": _mean(rec_deltas),
            "delta_mrr": _mean(rr_deltas),
            "delta_ndcg": _mean(ndcg_deltas),
            "n_scored_pairs": len(b_scores),
        },
    )
    print(f"results → {result_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
