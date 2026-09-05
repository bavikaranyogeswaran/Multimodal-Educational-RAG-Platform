"""Score retrieval against a gold set and report what it found.

Runs the real pipeline for every question — classify, rewrite, expand, dense and keyword
search, fusion, reranking, pruning, selection — and compares what came back against the
pages the answer is known to be on.

Two numbers matter most and they fail differently. Page recall says whether retrieval
reached everywhere the answer lives; phrase coverage says whether the particular thing
worth finding was actually in what came back. An aggregation can reach every page and
still name one library out of five, and only the second number says so.

The classifier's own verdict is reported beside the class the question was labelled with,
because a disagreement is the finding rather than a labelling error: a procedure and an
aggregation both fall through to the fallback today, and this is what makes that visible
per question instead of as an anecdote.

Usage:
    uv run python scripts/evaluate_retrieval.py <knowledge-base-id> [gold-set.json]
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from scripts._eval_store import save_run

from app.api.dependencies.retrieval import build_retrieval_orchestrator
from app.application.queries.retrieve_evidence import RetrieveEvidenceQuery
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.enums import QueryClass
from app.domain.evaluation.entities import GoldPair, GoldSet
from app.domain.evaluation.metrics import RetrievalScores, precision_at_k, score
from app.domain.retrieval.classifier import QueryClassifier
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.evaluation.gold_set_file import load_gold_set
from app.infrastructure.observability.structlog_setup import configure_structlog

_DEFAULT_GOLD = (
    Path(__file__).parent.parent / "evaluation" / "gold" / ("data-science-in-the-cloud.json")
)

#: The window recall, reciprocal rank and NDCG are reported over. Wide enough to say
#: whether the answer was found at all and how high it ranked.
_K = 10

_CLASSIFIER = QueryClassifier()


async def _run_one(
    orchestrator: object, scope: ScopeContext, pair: GoldPair
) -> tuple[RetrievalScores | None, float, QueryClass, int]:
    """Retrieve for one question and score it. Returns None for unanswerable pairs."""
    result = await orchestrator.execute(  # type: ignore[attr-defined]
        RetrieveEvidenceQuery(scope=scope, query=pair.question, filters=RetrievalFilters())
    )
    evidence = list(result.evidence)
    pages = [list(range(item.chunk.page_start, item.chunk.page_end + 1)) for item in evidence]
    texts = [item.chunk.text.value for item in evidence]

    # The orchestrator does not report the class it chose, so it is asked again here.
    # Rule-based and deterministic, so this cannot disagree with what the run did.
    classified = _CLASSIFIER.classify(pair.question)

    if pair.unanswerable:
        return None, 0.0, classified, len(evidence)

    return (
        score(
            pages,
            pair.gold_pages,
            k=_K,
            retrieved_text=texts,
            must_contain=pair.must_contain,
        ),
        _selection_precision(pages, pair.gold_pages),
        classified,
        len(evidence),
    )


def _selection_precision(pages: list[list[int]], gold: frozenset[int]) -> float:
    """Precision over what the pipeline chose to show, not over the search window.

    The selector returns far fewer passages than search found, on purpose — the evidence
    budget is a rule about questions rather than a shortfall. Dividing by a fixed window
    would score that decision as a failure to fill it, so a run returning four good
    passages out of ten slots would read as 0.4 precision when nothing was wrong.

    What is worth measuring instead is how much of what actually reached the prompt
    earned its place, because every passage that did not is one the model may answer from.
    """
    if not pages:
        return 0.0
    return precision_at_k(pages, gold, k=len(pages))


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)

    kb_id = UUID(sys.argv[1])
    gold_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_GOLD
    gold: GoldSet = load_gold_set(gold_path)

    settings = get_settings()
    # The pipeline logs a line per stage per question. Useful when chasing one
    # question, and 200 lines of noise over a whole set — run with
    # OBSERVABILITY_LOG_LEVEL=WARNING to read the table.
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
    print(f"window   : top {_K}\n")

    header = (
        f"{'pair':<24} {'labelled':<12} {'classified':<12} {'rec':>5} {'sel-p':>5} "
        f"{'rr':>5} {'ndcg':>5} {'phr':>5} {'n':>3}"
    )
    print(header)
    print("-" * len(header))

    scores: list[RetrievalScores] = []
    selections: list[float] = []
    disagreements: list[tuple[str, QueryClass, QueryClass]] = []
    per_class: dict[QueryClass, list[float]] = {}

    async with container.session_factory() as session:
        orchestrator = build_retrieval_orchestrator(container, settings, scope, session)
        for pair in gold.pairs:
            result, selection, classified, returned = await _run_one(orchestrator, scope, pair)
            if classified is not pair.expected_class:
                disagreements.append((pair.id, pair.expected_class, classified))

            if result is None:
                verdict = "found nothing" if returned == 0 else f"returned {returned}"
                print(
                    f"{pair.id:<24} {pair.expected_class.value:<12} "
                    f"{classified.value:<12} {'unanswerable — ' + verdict:>31}"
                )
                continue

            scores.append(result)
            selections.append(selection)
            per_class.setdefault(pair.expected_class, []).append(result.page_recall)
            print(
                f"{pair.id:<24} {pair.expected_class.value:<12} {classified.value:<12} "
                f"{result.page_recall:>5.2f} {selection:>5.2f} "
                f"{result.reciprocal_rank:>5.2f} {result.ndcg:>5.2f} "
                f"{result.phrases:>5.2f} {returned:>3}"
            )

    print(
        f"\n{'':<24} {'':<12} {'MEAN':<12} "
        f"{_mean([s.page_recall for s in scores]):>5.2f} "
        f"{_mean(selections):>5.2f} "
        f"{_mean([s.reciprocal_rank for s in scores]):>5.2f} "
        f"{_mean([s.ndcg for s in scores]):>5.2f} "
        f"{_mean([s.phrases for s in scores]):>5.2f}"
    )

    print("\npage recall by labelled class:")
    for query_class, values in sorted(per_class.items(), key=lambda kv: kv[0].value):
        print(f"  {query_class.value:<14} {_mean(values):.2f}  ({len(values)} pairs)")

    if disagreements:
        print(
            f"\nclassifier disagreed with the label on {len(disagreements)} of {len(gold.pairs)}:"
        )
        for pair_id, labelled, classified in disagreements:
            print(f"  {pair_id:<24} labelled {labelled.value}, classified {classified.value}")

    missing = sorted(c.value for c in set(QueryClass) - gold.classes_covered)
    print(
        f"\nclasses this set never asks about ({len(missing)} of {len(list(QueryClass))}): "
        f"{', '.join(missing)}"
    )

    result_path = save_run(
        "retrieval",
        kb_id,
        gold.source,
        {
            "page_recall": _mean([s.page_recall for s in scores]),
            "selection_precision": _mean(selections),
            "mrr": _mean([s.reciprocal_rank for s in scores]),
            "ndcg": _mean([s.ndcg for s in scores]),
            "phrase_coverage": _mean([s.phrases for s in scores]),
            "n_scored_pairs": len(scores),
        },
    )
    print(f"results → {result_path}")


if __name__ == "__main__":
    # Questions and source lines are printed as the gold set wrote them, and the console
    # encoding inherited here cannot always represent that. Substituting the character it
    # cannot write is the mild failure; without this the run stops at that row, and a
    # table of scores that ends early still reads like the whole set.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
