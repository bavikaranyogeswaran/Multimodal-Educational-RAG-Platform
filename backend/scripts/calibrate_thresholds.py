"""Sweep relative_score_margin and report retrieval latency vs NFR-PERF targets.

Two things the project cannot do without a live database run:

  1. Find the relative_score_margin that maximises retrieval quality on the gold
     set.  The current value (0.35) was chosen as a reasonable default; this
     script sweeps a configurable range and picks the value that maximises the
     mean of page recall, NDCG and phrase coverage.

  2. Measure actual retrieval latency (p50, p95) and compare it to NFR-PERF-07
     (retrieval through reranking ≤ 800 ms p95).  Timings are wall-clock from the
     point the orchestrator is called to the point it returns, captured once per
     gold-set pair at the best-margin value.

The script prints a sweep table, then a latency summary, then a recommendation.
If the best margin equals the current setting the .env file is already correct.

Usage:
    uv run python scripts/calibrate_thresholds.py <knowledge-base-id>
    uv run python scripts/calibrate_thresholds.py <kb-id> gold-set.json
    uv run python scripts/calibrate_thresholds.py <kb-id> --min 0.10 --max 0.50 --step 0.05
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.api.dependencies.retrieval import build_retrieval_orchestrator
from app.application.queries.retrieve_evidence import RetrieveEvidenceQuery
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.evaluation.metrics import RetrievalScores, score
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.evaluation.gold_set_file import load_gold_set
from app.infrastructure.observability.structlog_setup import configure_structlog
from scripts._eval_store import save_run

_DEFAULT_GOLD = (
    Path(__file__).parent.parent / "evaluation" / "gold" / "data-science-in-the-cloud.json"
)

_K = 10

# NFR-PERF-07: retrieval through reranking, excluding generation.
_NFR_P95_MS = 800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], p: int) -> float:
    """p-th percentile via linear interpolation (p in [1, 100])."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    rank = (p / 100.0) * (len(s) - 1)
    lo, hi = int(rank), min(int(rank) + 1, len(s) - 1)
    return s[lo] + (rank - lo) * (s[hi] - s[lo])


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _pages(evidence: list) -> list[list[int]]:
    return [list(range(e.chunk.page_start, e.chunk.page_end + 1)) for e in evidence]


def _texts(evidence: list) -> list[str]:
    return [e.chunk.text for e in evidence]


# ---------------------------------------------------------------------------
# One margin sweep step
# ---------------------------------------------------------------------------


async def _run_one_margin(
    container: object,
    settings: object,
    scope: ScopeContext,
    pairs: list,
    margin: float,
) -> tuple[list[RetrievalScores], list[float]]:
    """Run all pairs at one margin. Returns (scores_per_pair, elapsed_ms_per_pair)."""
    modified = settings.model_copy(  # type: ignore[attr-defined]
        update={
            "evidence": settings.evidence.model_copy(  # type: ignore[attr-defined]
                update={"relative_score_margin": margin}
            )
        }
    )

    scored: list[RetrievalScores] = []
    timings: list[float] = []

    async with container.session_factory() as session:  # type: ignore[attr-defined]
        orchestrator = build_retrieval_orchestrator(container, modified, scope, session)
        for pair in pairs:
            t0 = time.monotonic()
            result = await orchestrator.execute(
                RetrieveEvidenceQuery(scope=scope, query=pair.question, filters=RetrievalFilters())
            )
            timings.append((time.monotonic() - t0) * 1000.0)

            evidence = list(result.evidence)
            if not evidence:
                continue

            scored.append(
                score(
                    _pages(evidence),
                    pair.gold_pages,
                    k=min(_K, len(evidence)),
                    retrieved_text=_texts(evidence),
                    must_contain=pair.must_contain,
                )
            )

    return scored, timings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kb_id", type=UUID, metavar="knowledge-base-id")
    parser.add_argument("gold_path", nargs="?", default=None, metavar="gold-set.json")
    parser.add_argument("--min", dest="margin_min", type=float, default=0.10, metavar="MARGIN")
    parser.add_argument("--max", dest="margin_max", type=float, default=0.50, metavar="MARGIN")
    parser.add_argument("--step", dest="margin_step", type=float, default=0.05, metavar="STEP")
    args = parser.parse_args()

    kb_id: UUID = args.kb_id
    gold_path = Path(args.gold_path) if args.gold_path else _DEFAULT_GOLD
    gold = load_gold_set(gold_path)
    pairs = gold.answerable
    if not pairs:
        print("gold set has no answerable pairs — nothing to calibrate against")
        raise SystemExit(1)

    settings = get_settings()
    configure_structlog(settings)
    container = build_container(settings)

    async with container.session_factory() as session:  # type: ignore[attr-defined]
        user_id = (
            await session.execute(
                text("SELECT user_id FROM knowledge_bases WHERE id = :kb"),
                {"kb": kb_id},
            )
        ).scalar_one()

    scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
    current_margin: float = settings.evidence.relative_score_margin  # type: ignore[attr-defined]

    # Build the list of margins to sweep
    margins: list[float] = []
    v = args.margin_min
    while v <= args.margin_max + 1e-9:
        margins.append(round(v, 4))
        v += args.margin_step
    # Always include the current setting even if it falls outside the range
    if not any(abs(m - current_margin) < 1e-6 for m in margins):
        margins.append(current_margin)
        margins.sort()

    print(f"gold set     : {gold_path.name}")
    print(f"source       : {gold.source}")
    print(f"pairs        : {len(pairs)} answerable of {len(gold.pairs)} total")
    print(f"current      : EVIDENCE_RELATIVE_SCORE_MARGIN={current_margin:.2f}")
    print(f"sweep        : {args.margin_min:.2f} → {args.margin_max:.2f}  step {args.margin_step:.2f}")
    print()

    header = (
        f"  {'margin':>6}  "
        f"{'rec':>5} {'ndcg':>5} {'phr':>5}  "
        f"{'n_ev':>4}  "
        f"{'p50ms':>6} {'p95ms':>6}  "
        f"{'nfr07':>5}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    best_margin = current_margin
    best_combined = -1.0
    all_rows: list[dict] = []

    for margin in margins:
        scored, timings = await _run_one_margin(container, settings, scope, pairs, margin)
        if not scored:
            print(f"  {margin:>6.2f}  (no evidence returned — skip)")
            continue

        rec = _mean([s.page_recall for s in scored])
        ndcg = _mean([s.ndcg for s in scored])
        phr = _mean([s.phrases for s in scored])
        n_ev = _mean([float(s.returned) for s in scored])
        p50 = _percentile(timings, 50)
        p95 = _percentile(timings, 95)
        n_over = sum(1 for t in timings if t > _NFR_P95_MS)
        nfr07 = "PASS" if p95 <= _NFR_P95_MS else f"FAIL"

        combined = (rec + ndcg + phr) / 3.0
        if combined > best_combined:
            best_combined = combined
            best_margin = margin

        mark = "*" if abs(margin - current_margin) < 1e-6 else " "
        print(
            f"{mark} {margin:>6.2f}  "
            f"{rec:>5.2f} {ndcg:>5.2f} {phr:>5.2f}  "
            f"{n_ev:>4.1f}  "
            f"{p50:>6.0f} {p95:>6.0f}  "
            f"{nfr07:>5}"
        )

        all_rows.append({
            "margin": margin,
            "page_recall": rec,
            "ndcg": ndcg,
            "phrase_coverage": phr,
            "mean_evidence": n_ev,
            "p50_ms": p50,
            "p95_ms": p95,
            "n_over_nfr_07": n_over,
            "nfr07_pass": p95 <= _NFR_P95_MS,
        })

    if not all_rows:
        print("no scored rows — cannot calibrate")
        raise SystemExit(1)

    print(sep)
    print("  * = current setting\n")

    # ── Recommendation ──────────────────────────────────────────────────────
    best_row = next(r for r in all_rows if abs(r["margin"] - best_margin) < 1e-6)
    print(f"best margin (max mean rec+ndcg+phr) : {best_margin:.2f}")
    if abs(best_margin - current_margin) > 1e-6:
        print(
            f"recommendation : set EVIDENCE_RELATIVE_SCORE_MARGIN={best_margin:.2f}  "
            f"(current {current_margin:.2f})"
        )
    else:
        print(f"current margin {current_margin:.2f} is already the best — no .env change needed")

    # ── Latency summary ─────────────────────────────────────────────────────
    print(f"\nlatency at best margin {best_margin:.2f}:")
    print(f"  p50 = {best_row['p50_ms']:.0f} ms")
    p95_val = best_row["p95_ms"]
    target = _NFR_P95_MS
    print(
        f"  p95 = {p95_val:.0f} ms  (NFR-PERF-07 target: ≤ {target} ms)  "
        + ("PASS" if p95_val <= target else f"FAIL  +{p95_val - target:.0f} ms over")
    )

    # ── Persist ─────────────────────────────────────────────────────────────
    flat_scores: dict = {
        "best_margin": best_margin,
        "current_margin": current_margin,
        "best_page_recall": best_row["page_recall"],
        "best_ndcg": best_row["ndcg"],
        "best_phrase_coverage": best_row["phrase_coverage"],
        "best_p50_ms": best_row["p50_ms"],
        "best_p95_ms": best_row["p95_ms"],
        "nfr07_pass": best_row["nfr07_pass"],
        "n_sweep_steps": len(all_rows),
    }
    for row in all_rows:
        key = f"{row['margin']:.2f}"
        flat_scores[f"rec_{key}"] = row["page_recall"]
        flat_scores[f"ndcg_{key}"] = row["ndcg"]
        flat_scores[f"p95_ms_{key}"] = row["p95_ms"]

    result_path = save_run("calibration", kb_id, gold.source, flat_scores)
    print(f"\nresults → {result_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
