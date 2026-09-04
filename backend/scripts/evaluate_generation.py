"""Score generation quality against the gold set.

Runs the real retrieval and generation pipeline for every question and measures
what came out.  Three things can go wrong independently:

  parse     — the model produced text that is not valid JSON
  phrase    — the answer omits a phrase the question is known to require
  grounding — a claim cites a passage unrelated to the gold pages

They are reported separately because they fail differently.  A high phrase score
with low grounding means the model said the right things but lied about where
they came from.  A parse failure means nothing downstream could be checked.

Two special outcomes are tracked per pair:
  abstain — for unanswerable questions, did the model correctly say so?
  false_abstain — for answerable questions, did the model incorrectly refuse?

Grounding counts unique cited labels, not claims, so one multiply-cited passage
does not dominate.  A label is grounded if its evidence chunk touches any gold page.

This script does not run the post-generation validation pipeline (citation
existence checks, entailment, repair attempts).  It measures the model's
first-pass output so the scores are comparable between prompt versions without
the validator's corrections inflating the grounding numbers.

Usage:
    uv run python scripts/evaluate_generation.py <knowledge-base-id> [gold-set.json]
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from collections.abc import AsyncIterable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.api.dependencies.retrieval import build_retrieval_orchestrator
from app.application.commands.answer import (
    _INSTRUCTIONS,
    _SAFETY_RULES,
    _SYSTEM_PREAMBLE,
    _TASK_INSTRUCTIONS,
)
from app.application.queries.retrieve_evidence import RetrievalOrchestrator, RetrieveEvidenceQuery
from app.configuration.settings import get_settings
from app.configuration.wire import build_container
from app.domain.enums import ModelTask
from app.domain.evaluation.entities import GoldPair
from app.domain.errors import GenerationParseError
from app.domain.models.context_builder import ContextBuilder, ContextInputs
from app.domain.models.entities import LabeledPassage
from app.domain.models.generation import OUTPUT_SCHEMA, GeneratedAnswer, parse_generated_answer
from app.domain.retrieval.entities import Evidence, RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.evaluation.gold_set_file import load_gold_set
from app.infrastructure.observability.structlog_setup import configure_structlog

_DEFAULT_GOLD = (
    Path(__file__).parent.parent / "evaluation" / "gold" / "data-science-in-the-cloud.json"
)


@dataclass
class _RunResult:
    answer: GeneratedAnswer | None
    parse_ok: bool
    evidence: list[Evidence]

    @property
    def n_evidence(self) -> int:
        return len(self.evidence)


async def _drain(stream: AsyncIterable[str]) -> str:
    parts: list[str] = []
    async for token in stream:
        parts.append(token)
    return "".join(parts)


def _label_evidence(evidence: Sequence[Evidence]) -> tuple[LabeledPassage, ...]:
    return tuple(
        LabeledPassage(label=item.label.bracketed, text=item.chunk.text) for item in evidence
    )


def _phrase_coverage(answer_text: str, must_contain: Collection[str]) -> float:
    if not must_contain:
        return 1.0
    lower = answer_text.lower()
    return sum(1 for phrase in must_contain if phrase.lower() in lower) / len(must_contain)


def _citation_grounding(
    answer: GeneratedAnswer,
    evidence: list[Evidence],
    gold_pages: frozenset[int],
) -> float | None:
    """Fraction of unique cited labels whose chunk touches a gold page.

    Returns None when the answer makes no citations (e.g. when it abstained).
    """
    label_map = {e.label.bracketed: e for e in evidence}
    cited = {label for claim in answer.claims for label in claim.citations}
    if not cited:
        return None
    grounded = 0
    for label in cited:
        ev = label_map.get(label)
        if ev is None:
            continue  # hallucinated label: not in the evidence set
        chunk_pages = set(range(ev.chunk.page_start, ev.chunk.page_end + 1))
        if chunk_pages & gold_pages:
            grounded += 1
    return grounded / len(cited)


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


async def _run_one(
    orchestrator: RetrievalOrchestrator,
    gateway: object,
    context_builder: ContextBuilder,
    scope: ScopeContext,
    pair: GoldPair,
) -> _RunResult:
    retrieval = await orchestrator.execute(
        RetrieveEvidenceQuery(scope=scope, query=pair.question, filters=RetrievalFilters())
    )
    evidence = list(retrieval.evidence)
    labeled = _label_evidence(evidence)

    request = context_builder.build(
        ContextInputs(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=_SAFETY_RULES,
            task_instructions=_TASK_INSTRUCTIONS,
            query=pair.question,
            instructions=_INSTRUCTIONS,
            evidence=labeled,
            output_schema=OUTPUT_SCHEMA,
        )
    )

    raw = await _drain(gateway.generate_stream(request))  # type: ignore[attr-defined]

    try:
        answer = parse_generated_answer(raw)
        return _RunResult(answer=answer, parse_ok=True, evidence=evidence)
    except GenerationParseError:
        return _RunResult(answer=None, parse_ok=False, evidence=evidence)


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
    context_builder = ContextBuilder(
        container.token_counter.count,  # type: ignore[attr-defined]
        token_budget=settings.model.prompt_token_budget,  # type: ignore[attr-defined]
    )

    print(f"gold set : {gold_path.name}")
    print(f"source   : {gold.source}")
    print(f"pairs    : {len(gold.pairs)} ({len(gold.answerable)} answerable)")
    print(f"model    : {type(container.model_gateway).__name__}\n")  # type: ignore[attr-defined]

    col = 24
    header = (
        f"{'pair':<{col}}  "
        f"{'phr':>5} {'cit_g':>5} {'abst':>5}  "
        f"{'clm':>4} {'wds':>4}  "
        f"{'ev':>3}  {'parse':>5}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    phrase_scores: list[float] = []
    grounding_scores: list[float] = []
    abstain_correct: list[bool] = []
    false_abstains = 0
    parse_failures = 0

    async with container.session_factory() as session:
        orchestrator = build_retrieval_orchestrator(container, settings, scope, session)
        for pair in gold.pairs:
            run = await _run_one(
                orchestrator,
                container.model_gateway,  # type: ignore[attr-defined]
                context_builder,
                scope,
                pair,
            )

            if not run.parse_ok:
                parse_failures += 1
                print(
                    f"{pair.id:<{col}}  "
                    f"{'—':>5} {'—':>5} {'—':>5}  "
                    f"{'—':>4} {'—':>4}  "
                    f"{run.n_evidence:>3}  {'FAIL':>5}"
                )
                continue

            answer = run.answer
            assert answer is not None

            if pair.unanswerable:
                correct = answer.insufficient_evidence
                abstain_correct.append(correct)
                abst_str = "✓" if correct else "✗"
                print(
                    f"{pair.id:<{col}}  "
                    f"{'—':>5} {'—':>5} {abst_str:>5}  "
                    f"{len(answer.claims):>4} {len(answer.answer.split()):>4}  "
                    f"{run.n_evidence:>3}  {'ok':>5}"
                )
                continue

            phr = _phrase_coverage(answer.answer, pair.must_contain)
            cit_g = _citation_grounding(answer, run.evidence, pair.gold_pages)
            phrase_scores.append(phr)
            if cit_g is not None:
                grounding_scores.append(cit_g)

            if answer.insufficient_evidence:
                false_abstains += 1
                abst_str = "FA"
            else:
                abst_str = "—"

            cit_str = f"{cit_g:.2f}" if cit_g is not None else "—"
            print(
                f"{pair.id:<{col}}  "
                f"{phr:>5.2f} {cit_str:>5} {abst_str:>5}  "
                f"{len(answer.claims):>4} {len(answer.answer.split()):>4}  "
                f"{run.n_evidence:>3}  {'ok':>5}"
            )

    print(sep)
    print(
        f"{'MEAN':<{col}}  "
        f"{_mean(phrase_scores):>5.2f} "
        f"{_mean(grounding_scores):>5.2f}"
    )

    n_ans = len(gold.answerable)
    n_unans = len(gold.pairs) - n_ans
    abs_ok = sum(1 for x in abstain_correct if x)

    print(f"\nphrase coverage  : {_mean(phrase_scores):.3f}  (mean, {len(phrase_scores)} answerable pairs)")
    if grounding_scores:
        print(f"cit grounding    : {_mean(grounding_scores):.3f}  (mean, {len(grounding_scores)} pairs with citations)")
    if n_unans:
        print(f"abstain correct  : {abs_ok}/{n_unans}  (unanswerable pairs correctly refused)")
    if false_abstains:
        print(f"false abstain    : {false_abstains}/{n_ans}  (answerable pairs incorrectly refused)")
    print(f"parse failures   : {parse_failures}/{len(gold.pairs)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
