"""Score the multi-hop pipeline on decomposable gold-set questions.

Filters the gold set to questions whose class requires decomposition
(AGGREGATION, COMPARISON, MULTI_HOP, MULTI_DOCUMENT) and runs each through the
full four-stage pipeline: decompose → iterative retrieval → evidence selection →
hierarchical synthesis.

Metrics per pair:
  phr   — phrase coverage of the synthesised final answer
  subs  — number of sub-questions the decomposer produced
  cov   — fraction of sub-questions rated SUPPORTED by the coverage classifier
  wds   — word count of the final answer

Results are compared against the same gold set used by evaluate_retrieval.py and
evaluate_generation.py, so the numbers are on a consistent footing.

Only decomposable-class pairs are scored; DIRECT, SUMMARY and unanswerable pairs
are skipped.  If the gold set has no decomposable pairs (e.g. a narrow domain set)
the script exits cleanly after saying so.

Usage:
    uv run python scripts/evaluate_multi_hop.py <knowledge-base-id> [gold-set.json]
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections.abc import Collection
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from scripts._eval_store import save_run

from app.api.dependencies.retrieval import build_retrieval_orchestrator
from app.application.commands.decompose import DecomposeQueryUseCase
from app.application.commands.multi_hop_answer import MultiHopAnswerCommand, MultiHopAnswerUseCase
from app.application.queries.coverage_classifier import CoverageClassifier
from app.application.queries.document_selection import DocumentSelector
from app.application.queries.evidence_selector import EvidenceSelector
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer
from app.application.queries.iterative_retrieval import IterativeRetrievalLoop
from app.application.queries.sub_question_pipeline import SubQuestionPipeline
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.enums import CoverageStatus
from app.domain.evaluation.entities import GoldPair
from app.domain.scope import ScopeContext
from app.infrastructure.evaluation.gold_set_file import load_gold_set
from app.infrastructure.observability.structlog_setup import configure_structlog

_DEFAULT_GOLD = (
    Path(__file__).parent.parent / "evaluation" / "gold" / "data-science-in-the-cloud.json"
)


def _phrase_coverage(answer_text: str, must_contain: Collection[str]) -> float:
    if not must_contain:
        return 1.0
    lower = answer_text.lower()
    return sum(1 for phrase in must_contain if phrase.lower() in lower) / len(must_contain)


def _coverage_fraction(sub_answers: object) -> float:
    """Fraction of sub-questions rated SUPPORTED."""
    items = list(sub_answers)  # type: ignore[call-overload]
    if not items:
        return 0.0
    return sum(1 for item in items if item.coverage is CoverageStatus.SUPPORTED) / len(items)


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)

    kb_id = UUID(sys.argv[1])
    gold_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_GOLD
    gold = load_gold_set(gold_path)

    pairs = [p for p in gold.pairs if p.expected_class.needs_decomposition and not p.unanswerable]
    if not pairs:
        print(f"gold set has no decomposable-class pairs — nothing to score")
        raise SystemExit(0)

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
    print(f"pairs    : {len(pairs)} decomposable of {len(gold.pairs)} total\n")

    col = 24
    header = (
        f"{'pair':<{col}}  {'class':<14}  "
        f"{'phr':>5} {'cov':>5} {'subs':>4} {'wds':>5}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    phrase_scores: list[float] = []
    cov_scores: list[float] = []
    sub_counts: list[int] = []

    async with container.session_factory() as session:
        orchestrator = build_retrieval_orchestrator(container, settings, scope, session)
        use_case = MultiHopAnswerUseCase(
            decompose=DecomposeQueryUseCase(container.query_decomposition),  # type: ignore[attr-defined]
            loop=IterativeRetrievalLoop(
                pipeline=SubQuestionPipeline(orchestrator),
                classifier=CoverageClassifier(container.coverage_classifier),  # type: ignore[attr-defined]
                selector=DocumentSelector(
                    max_documents=settings.multihop.max_documents_per_round,  # type: ignore[attr-defined]
                ),
            ),
            selector=EvidenceSelector(
                max_per_sub_question=settings.evidence.max_items,  # type: ignore[attr-defined]
            ),
            synthesizer=HierarchicalSynthesizer(container.multi_hop_synthesis),  # type: ignore[attr-defined]
        )

        for pair in pairs:
            result = await use_case.execute(
                MultiHopAnswerCommand(scope=scope, query=pair.question)
            )

            phr = _phrase_coverage(result.answer, pair.must_contain)
            cov = _coverage_fraction(result.sub_answers)
            n_subs = len(result.sub_answers)
            n_words = len(result.answer.split())

            phrase_scores.append(phr)
            cov_scores.append(cov)
            sub_counts.append(n_subs)

            print(
                f"{pair.id:<{col}}  {pair.expected_class.value:<14}  "
                f"{phr:>5.2f} {cov:>5.2f} {n_subs:>4} {n_words:>5}"
            )

    print(sep)
    print(
        f"{'MEAN':<{col}}  {'':14}  "
        f"{_mean(phrase_scores):>5.2f} {_mean(cov_scores):>5.2f} "
        f"{_mean([float(x) for x in sub_counts]):>4.1f}"
    )

    print(f"\nphrase coverage  : {_mean(phrase_scores):.3f}  (mean over {len(phrase_scores)} pairs)")
    print(f"sub-q coverage   : {_mean(cov_scores):.3f}  (fraction rated SUPPORTED)")
    print(f"mean sub-q count : {_mean([float(x) for x in sub_counts]):.1f}")

    # per-class breakdown
    by_class: dict[str, list[float]] = {}
    for pair, phr in zip(pairs, phrase_scores):
        by_class.setdefault(pair.expected_class.value, []).append(phr)
    if len(by_class) > 1:
        print("\nphrase coverage by class:")
        for cls, values in sorted(by_class.items()):
            print(f"  {cls:<16} {_mean(values):.2f}  ({len(values)} pairs)")

    result_path = save_run(
        "multi_hop",
        kb_id,
        gold.source,
        {
            "phrase_coverage": _mean(phrase_scores),
            "sub_q_supported_rate": _mean(cov_scores),
            "mean_sub_questions": _mean([float(x) for x in sub_counts]),
            "n_scored_pairs": len(pairs),
        },
    )
    print(f"results → {result_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
