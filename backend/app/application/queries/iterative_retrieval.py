"""Iterative retrieval loop for multi-hop queries.

After the first retrieval pass, some sub-questions may be left UNSUPPORTED or
PARTIALLY_SUPPORTED. This module drives up to max_rounds additional retrieval
passes for those sub-questions, narrowing the search to documents that have
already proved relevant via DocumentSelector.

CONFLICTING sub-questions are not re-retrieved — conflicting evidence is
surfaced in synthesis, not resolved by fetching more of it.

Each round beyond the first:
  1. Selects the most relevant documents from all evidence accumulated so far.
  2. Rebuilds a plan containing only the still-pending sub-questions (their
     upstream dependencies are already satisfied, so cross-dependencies are
     cleared for the retry plan).
  3. Re-runs the pipeline restricted to the selected document set.
  4. Re-classifies coverage and updates the status for each sub-question.

The loop stops when all sub-questions are SUPPORTED or CONFLICTING, or when
max_rounds is exhausted — whichever comes first.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.application.queries.coverage_classifier import CoverageClassifier, SubQuestionCoverage
from app.application.queries.document_selection import DocumentSelector
from app.application.queries.sub_question_pipeline import SubQuestionPipeline, SubQuestionResult
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)

_DEFAULT_MAX_ROUNDS = 3


@dataclass(frozen=True)
class IterativeRetrievalResult:
    """Final coverage state and how many retrieval rounds were actually executed."""

    coverages: list[SubQuestionCoverage]
    rounds_run: int


class IterativeRetrievalLoop:
    """Drive multi-round retrieval until all sub-questions are covered or max_rounds hit.

    Round 1 retrieves evidence for every sub-question in the plan. Subsequent rounds
    re-run only the ones that still need improvement, narrowed to the document set
    selected from all evidence gathered so far.
    """

    def __init__(
        self,
        pipeline: SubQuestionPipeline,
        classifier: CoverageClassifier,
        selector: DocumentSelector,
    ) -> None:
        self._pipeline = pipeline
        self._classifier = classifier
        self._selector = selector

    async def run(
        self,
        plan: DecompositionPlan,
        scope: ScopeContext,
        *,
        filters: RetrievalFilters | None = None,
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
    ) -> IterativeRetrievalResult:
        """Run up to max_rounds of retrieval, updating coverage after each round.

        Returns coverages in the same order as plan.sub_questions.
        """
        if max_rounds < 1:
            raise ValueError(f"max_rounds must be at least 1, got {max_rounds}")

        # Round 1 — full plan, caller-supplied filters (if any).
        results = await self._pipeline.run_all(plan, scope, filters=filters)
        coverages = await self._classifier.classify_all(results)
        coverage_map: dict[str, SubQuestionCoverage] = {c.sub_question.id: c for c in coverages}
        accumulated: list[SubQuestionResult] = list(results)
        rounds_run = 1

        _log.info(
            "iterative_retrieval.round_complete",
            round=1,
            total=len(plan.sub_questions),
            pending=sum(1 for c in coverages if c.needs_another_round),
        )

        for _ in range(max_rounds - 1):
            pending = [c for c in coverage_map.values() if c.needs_another_round]
            if not pending:
                break

            # Select the most relevant documents from all evidence gathered so far.
            selection = self._selector.select(accumulated)
            retry_filters = RetrievalFilters(document_ids=selection.selected_ids)

            # Strip cross-dependencies — upstream sub-questions are already satisfied.
            retry_sqs = [
                SubQuestion(id=c.sub_question.id, text=c.sub_question.text)
                for c in pending
            ]
            retry_plan = DecompositionPlan.build(plan.original_query, retry_sqs)

            retry_results = await self._pipeline.run_all(retry_plan, scope, filters=retry_filters)
            accumulated.extend(retry_results)

            new_coverages = await self._classifier.classify_all(retry_results)
            for c in new_coverages:
                coverage_map[c.sub_question.id] = c

            rounds_run += 1
            _log.info(
                "iterative_retrieval.round_complete",
                round=rounds_run,
                total=len(plan.sub_questions),
                pending=sum(1 for c in new_coverages if c.needs_another_round),
            )

        ordered = [coverage_map[sq.id] for sq in plan.sub_questions]
        return IterativeRetrievalResult(coverages=ordered, rounds_run=rounds_run)
