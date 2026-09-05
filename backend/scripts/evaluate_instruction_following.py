"""Check that generated answers comply with the structural instructions.

Runs the retrieval and generation pipeline (same as evaluate_generation.py but
without post-generation validation) and verifies the raw model output against the
rules the instructions impose.  Each check is structural — no additional model
calls, no human judgment.

Checks (per pair):
  labels_ok   — every cited label is within [S1]..[Sn] for n evidence items
                 (a label beyond range is a hallucinated source that does not exist)
  length_ok   — answer word count is within the configured answer_max_words limit
  uncited_ok  — all claims carry at least one citation
                 (structurally enforced by the parser, but confirmed explicitly)
  schema_ok   — the model produced valid JSON (same as parse_ok in evaluate_generation)

A row can pass label, length and uncited checks while failing schema — those
checks only run when parsing succeeds.  If the model never produces invalid JSON
the schema failure rate here and in evaluate_generation.py should match.

Usage:
    uv run python scripts/evaluate_instruction_following.py <knowledge-base-id> [gold-set.json]
"""

from __future__ import annotations

import asyncio
import re
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

_LABEL_RE = re.compile(r"\[S(\d+)\]")


@dataclass
class _Checks:
    schema_ok: bool
    labels_ok: bool | None   # None when schema failed (nothing to check)
    length_ok: bool | None
    uncited_ok: bool | None
    n_evidence: int
    n_words: int
    n_claims: int
    max_label: int | None    # highest Sn cited; None when no citations


async def _drain(stream: AsyncIterable[str]) -> str:
    parts: list[str] = []
    async for token in stream:
        parts.append(token)
    return "".join(parts)


def _label_evidence(evidence: Sequence[Evidence]) -> tuple[LabeledPassage, ...]:
    return tuple(
        LabeledPassage(label=item.label.bracketed, text=item.chunk.text) for item in evidence
    )


def _check(
    answer: GeneratedAnswer,
    n_evidence: int,
    max_words: int,
) -> _Checks:
    all_labels = [
        int(m.group(1))
        for claim in answer.claims
        for m in _LABEL_RE.finditer(" ".join(claim.citations))
    ]

    labels_ok = all(1 <= n <= n_evidence for n in all_labels) if all_labels else True
    length_ok = len(answer.answer.split()) <= max_words
    uncited_ok = all(bool(claim.citations) for claim in answer.claims)

    return _Checks(
        schema_ok=True,
        labels_ok=labels_ok,
        length_ok=length_ok,
        uncited_ok=uncited_ok,
        n_evidence=n_evidence,
        n_words=len(answer.answer.split()),
        n_claims=len(answer.claims),
        max_label=max(all_labels) if all_labels else None,
    )


async def _run_one(
    orchestrator: RetrievalOrchestrator,
    gateway: object,
    context_builder: ContextBuilder,
    scope: ScopeContext,
    pair: GoldPair,
    max_words: int,
) -> _Checks:
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
        return _check(answer, len(evidence), max_words)
    except GenerationParseError:
        return _Checks(
            schema_ok=False,
            labels_ok=None,
            length_ok=None,
            uncited_ok=None,
            n_evidence=len(evidence),
            n_words=0,
            n_claims=0,
            max_label=None,
        )


def _ok(value: bool | None) -> str:
    if value is None:
        return "—"
    return "✓" if value else "✗"


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


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
    max_words: int = settings.generation.answer_max_words  # type: ignore[attr-defined]

    print(f"gold set    : {gold_path.name}")
    print(f"source      : {gold.source}")
    print(f"pairs       : {len(gold.pairs)}")
    print(f"word limit  : {max_words} words\n")

    col = 24
    header = (
        f"{'pair':<{col}}  "
        f"{'schema':>6} {'labels':>6} {'length':>6} {'uncited':>7}  "
        f"{'wds':>4} {'ev':>3} {'clm':>3} {'max_S':>5}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    all_checks: list[_Checks] = []

    async with container.session_factory() as session:
        orchestrator = build_retrieval_orchestrator(container, settings, scope, session)

        for pair in gold.pairs:
            checks = await _run_one(
                orchestrator,
                container.model_gateway,  # type: ignore[attr-defined]
                context_builder,
                scope,
                pair,
                max_words,
            )
            all_checks.append(checks)

            max_s_str = str(checks.max_label) if checks.max_label is not None else "—"
            print(
                f"{pair.id:<{col}}  "
                f"{_ok(checks.schema_ok):>6} {_ok(checks.labels_ok):>6} "
                f"{_ok(checks.length_ok):>6} {_ok(checks.uncited_ok):>7}  "
                f"{checks.n_words:>4} {checks.n_evidence:>3} {checks.n_claims:>3} {max_s_str:>5}"
            )

    n = len(all_checks)
    schema_ok = sum(1 for c in all_checks if c.schema_ok)
    checked = [c for c in all_checks if c.schema_ok]
    labels_ok = sum(1 for c in checked if c.labels_ok)
    length_ok = sum(1 for c in checked if c.length_ok)
    uncited_ok = sum(1 for c in checked if c.uncited_ok)

    print(sep)
    print(f"\nschema valid   : {schema_ok}/{n}")
    print(f"labels in range: {labels_ok}/{len(checked)}  (of {len(checked)} parseable)")
    print(f"within limit   : {length_ok}/{len(checked)}  ({max_words}-word cap)")
    print(f"all cited      : {uncited_ok}/{len(checked)}")

    if checked:
        mean_words = _mean([float(c.n_words) for c in checked])
        mean_claims = _mean([float(c.n_claims) for c in checked])
        mean_ev = _mean([float(c.n_evidence) for c in checked])
        print(f"\nmean words     : {mean_words:.0f}")
        print(f"mean claims    : {mean_claims:.1f}")
        print(f"mean evidence  : {mean_ev:.1f}")
        label_violations = [c for c in checked if c.labels_ok is False]
        if label_violations:
            print(f"\n{len(label_violations)} pair(s) cited out-of-range labels:")
            for idx, pair in enumerate(gold.pairs):
                c = all_checks[idx]
                if c.schema_ok and c.labels_ok is False:
                    print(f"  {pair.id:<{col}}  max_S={c.max_label}  evidence={c.n_evidence}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
