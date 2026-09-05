"""Probe the memory retrieval system against the gold-set questions.

For every answerable gold question, runs the same memory-retrieval path the
answer pipeline runs in production — exact-key lookup, dense+keyword search,
RRF fusion — and reports what the model would have seen as memory context.

This is a retrieval probe, not a scored evaluation: memory quality cannot be
judged without a memory gold set (a file mapping each question to the facts
that should surface).  What the script CAN report is:

  • Total active facts and embedding coverage for the knowledge base.
  • Per-question: how many facts were pinned vs relevant, and whether any
    surfaced fact contains a phrase the answer is known to require.
  • Summary: fraction of questions where at least one memory fact surfaced.

If the knowledge base has no stored memory facts the results will be all zeros
— that is the correct answer for a fresh knowledge base with no prior turns.
To populate memory, run the answer API for at least one conversation turn with
a knowledge-base-aware memory extractor wired in (MEMORY_ENABLED=true in your
environment).

Usage:
    uv run python scripts/evaluate_memory.py <knowledge-base-id> [gold-set.json]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.application.commands.answer import _load_memory_context
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.scope import ScopeContext
from app.infrastructure.database.repositories.memory import SqlMemoryRepository
from app.infrastructure.database.repositories.conversation_summary import (
    SqlConversationSummaryRepository,
)
from app.infrastructure.evaluation.gold_set_file import load_gold_set
from app.infrastructure.observability.structlog_setup import configure_structlog

_DEFAULT_GOLD = (
    Path(__file__).parent.parent / "evaluation" / "gold" / "data-science-in-the-cloud.json"
)


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

    # ── Fact inventory ────────────────────────────────────────────────────────
    async with container.session_factory() as session:
        memory_repo = SqlMemoryRepository(scope=scope, session=session)
        all_facts = list(await memory_repo.list_all(scope))
        active_facts = list(await memory_repo.list_active(scope))

    n_all = len(all_facts)
    n_active = len(active_facts)
    n_embedded = sum(1 for f in active_facts if f.embedding is not None)

    print(f"gold set : {gold_path.name}")
    print(f"source   : {gold.source}")
    print(f"pairs    : {len(gold.pairs)} ({len(gold.answerable)} answerable)\n")

    print(f"memory facts (all)    : {n_all}")
    print(f"memory facts (active) : {n_active}")
    print(f"embedding coverage    : {n_embedded}/{n_active}", end="")
    if n_active:
        print(f"  ({n_embedded / n_active:.0%})")
    else:
        print()

    if n_active == 0:
        print(
            "\nNo active memory facts found for this knowledge base.\n"
            "Run at least one answer turn with memory extraction enabled to populate memory."
        )
        return

    print()

    col = 24
    header = (
        f"{'pair':<{col}}  "
        f"{'pinned':>6} {'relev':>5}  {'phrase_hit':>10}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    pairs_with_any: list[str] = []
    pairs_with_phrase_hit: list[str] = []

    async with container.session_factory() as session:
        memory_repo = SqlMemoryRepository(scope=scope, session=session)
        summary_repo = SqlConversationSummaryRepository(scope=scope, session=session)

        for pair in gold.answerable:
            pinned, relevant = await _load_memory_context(
                scope,
                pair.question,
                memory_repo,
                container.embedder,  # type: ignore[attr-defined]
                summary_repo=summary_repo,
            )

            n_pinned = len(pinned)
            n_relevant = len(relevant)

            if n_pinned + n_relevant > 0:
                pairs_with_any.append(pair.id)

            # Check if any surfaced fact text mentions the expected phrases.
            # `pinned` and `relevant` are plain strings, not MemoryFact objects.
            all_surfaced_text = " ".join(list(pinned) + list(relevant)).lower()
            phrase_hits = [
                phrase for phrase in pair.must_contain
                if phrase.lower() in all_surfaced_text
            ]

            if phrase_hits:
                pairs_with_phrase_hit.append(pair.id)
                hit_str = f"{len(phrase_hits)}/{len(pair.must_contain)}"
            elif pair.must_contain:
                hit_str = f"0/{len(pair.must_contain)}"
            else:
                hit_str = "—"

            print(
                f"{pair.id:<{col}}  "
                f"{n_pinned:>6} {n_relevant:>5}  {hit_str:>10}"
            )

    print(sep)
    n_ans = len(gold.answerable)
    print(f"\nmemory surfaced  : {len(pairs_with_any)}/{n_ans} questions had at least one fact")
    if any(p.must_contain for p in gold.answerable):
        print(f"phrase in memory : {len(pairs_with_phrase_hit)}/{n_ans} questions had a required phrase in memory")
    print(
        "\nNote: this is a retrieval probe — whether surfaced facts improve the answer\n"
        "requires a memory gold set mapping each question to expected facts."
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
