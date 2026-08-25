"""Run one question and show what reached the prompt, and what it scored on the way.

The companion to `evaluate_retrieval.py`. A score says a question failed; this says how,
and the three answers are different repairs: the passage was never found, it was found
and ranked below the cut, or it was found, ranked well, and dropped by the selector.

Naming the gold pages marks the passages that should have come back, so a run that looks
plausible and is wrong is visible as one.

Usage:
    uv run python scripts/explain_retrieval.py <kb-id> "<question>" [gold-pages]

    uv run python scripts/explain_retrieval.py 4e2a161e-... \\
        "Which Python libraries does this report use?" 12,20,21
"""

from __future__ import annotations

import asyncio
import sys
from uuid import UUID

from sqlalchemy import text

from app.api.dependencies.retrieval import build_retrieval_orchestrator
from app.application.queries.retrieve_evidence import RetrieveEvidenceQuery
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.retrieval.classifier import QueryClassifier
from app.domain.retrieval.entities import RetrievalFilters

# Read directly rather than through the selector, which needs a token counter and a
# settings object to build. This only wants to report the budget, not apply it.
from app.domain.retrieval.selector import _DEFAULT_RANGES
from app.domain.scope import ScopeContext


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)

    kb_id = UUID(sys.argv[1])
    question = sys.argv[2]
    gold = {int(p) for p in sys.argv[3].split(",")} if len(sys.argv) > 3 else set()

    settings = get_settings()
    container = build_container(settings)

    async with container.session_factory() as session:
        user_id = (
            await session.execute(
                text("SELECT user_id FROM knowledge_bases WHERE id = :kb"), {"kb": kb_id}
            )
        ).scalar_one()

    scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
    query_class = QueryClassifier().classify(question)
    budget = _DEFAULT_RANGES[query_class]

    print(f"question   : {question}")
    print(f"classified : {query_class.value}")
    print(f"budget     : {budget.minimum}-{budget.maximum} passages")
    print(f"gold pages : {sorted(gold) or '(none given)'}")

    async with container.session_factory() as session:
        orchestrator = build_retrieval_orchestrator(container, settings, scope, session)
        result = await orchestrator.execute(
            RetrieveEvidenceQuery(scope=scope, query=question, filters=RetrievalFilters())
        )

    print(f"rewritten  : {result.standalone_query!r} (rewritten={result.was_rewritten})")
    print(f"\n{len(result.evidence)} passages reached the prompt:")
    for item in result.evidence:
        pages = set(range(item.chunk.page_start, item.chunk.page_end + 1))
        # A passage the ranking disliked and the class minimum kept anyway is the case
        # worth seeing: it is in the prompt because of the budget, not the ranking.
        mark = "HIT " if pages & gold else "    "
        rerank = "none" if item.rerank_score is None else f"{item.rerank_score:+.3f}"
        print(
            f"  {mark}p{item.chunk.page_start}-{item.chunk.page_end} "
            f"[{item.chunk.chunk_type.value}] rerank={rerank}"
        )
        print(f"       {' '.join(item.chunk.text.value.split())[:110]}")

    if gold:
        reached = {
            page
            for item in result.evidence
            for page in range(item.chunk.page_start, item.chunk.page_end + 1)
        }
        missed = sorted(gold - reached)
        print(f"\ngold pages not reached: {missed or 'none'}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
