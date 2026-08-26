"""Run the full retrieval pipeline for each sub-question in a decomposition plan.

Independent sub-questions — those whose dependencies are all satisfied by a prior
topological level — are dispatched concurrently within their level. Dependent ones
wait until every sub-question they reference has been retrieved.

The parallelism is entirely at the asyncio level: the sub-questions go to
asyncio.gather in batches, and each batch runs while the event loop is free to
drive the individual awaits inside each RetrievalOrchestrator call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from app.application.queries.retrieve_evidence import RetrievalOrchestrator, RetrieveEvidenceQuery
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.retrieval.entities import Evidence, RetrievalFilters
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SubQuestionResult:
    """Retrieval outcome for one sub-question.

    `standalone_query` is the rewritten form the orchestrator actually searched for.
    It may differ from `sub_question.text` when a query rewriter was in the pipeline.
    Evidence is the ranked, labelled set ready for the context builder.
    """

    sub_question: SubQuestion
    evidence: Sequence[Evidence]
    standalone_query: str


class SubQuestionPipeline:
    """Retrieve evidence for every sub-question in a plan.

    Each sub-question goes through the same full pipeline as a single-turn query:
    classify → rewrite → expand → embed → search → fuse → rerank → prune →
    expand parents → select → compress. This re-uses RetrievalOrchestrator unchanged.

    Sub-questions at the same topological level (no dependency between them) are
    dispatched in parallel; each level completes before the next begins.
    """

    def __init__(self, orchestrator: RetrievalOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def run_all(
        self,
        plan: DecompositionPlan,
        scope: ScopeContext,
        *,
        filters: RetrievalFilters | None = None,
    ) -> list[SubQuestionResult]:
        """Run retrieval for every sub-question, parallelising independent ones.

        Returns results in the same topological order as `plan.sub_questions` —
        dependencies always appear before the sub-questions that depend on them.
        """
        applied_filters = filters or RetrievalFilters()
        levels = _topological_levels(plan)
        results_by_id: dict[str, SubQuestionResult] = {}

        for level_index, level in enumerate(levels):
            _log.debug(
                "sub_question_pipeline.level",
                level=level_index,
                count=len(level),
                ids=[sq.id for sq in level],
            )
            level_results = await asyncio.gather(
                *[self._run_one(sq, scope, applied_filters) for sq in level]
            )
            for result in level_results:
                results_by_id[result.sub_question.id] = result

        return [results_by_id[sq.id] for sq in plan.sub_questions]

    async def _run_one(
        self,
        sub_question: SubQuestion,
        scope: ScopeContext,
        filters: RetrievalFilters,
    ) -> SubQuestionResult:
        result = await self._orchestrator.execute(
            RetrieveEvidenceQuery(
                scope=scope,
                query=sub_question.text,
                filters=filters,
            )
        )
        _log.debug(
            "sub_question_pipeline.retrieved",
            sub_question_id=sub_question.id,
            evidence_count=len(list(result.evidence)),
            was_rewritten=result.was_rewritten,
        )
        return SubQuestionResult(
            sub_question=sub_question,
            evidence=result.evidence,
            standalone_query=result.standalone_query,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _topological_levels(plan: DecompositionPlan) -> list[list[SubQuestion]]:
    """Group sub-questions into dependency layers for concurrent dispatch.

    All items within one level are safe to run in parallel: they share no direct
    or transitive dependency on each other. A sub-question's level is one more than
    the maximum level of its dependencies. Level 0 holds the items with no dependencies.

    The plan is already topologically sorted, so iterating in order gives each
    sub-question a level that is always ≥ the level of every dependency it names.
    """
    level_map: dict[str, int] = {}
    for sq in plan.sub_questions:
        if not sq.depends_on:
            level_map[sq.id] = 0
        else:
            level_map[sq.id] = max(level_map[dep] for dep in sq.depends_on) + 1

    if not level_map:
        return []

    max_level = max(level_map.values())
    levels: list[list[SubQuestion]] = [[] for _ in range(max_level + 1)]
    for sq in plan.sub_questions:
        levels[level_map[sq.id]].append(sq)
    return levels
