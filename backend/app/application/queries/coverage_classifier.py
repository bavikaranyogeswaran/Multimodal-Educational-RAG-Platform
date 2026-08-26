"""Classify how well retrieved evidence covers each sub-question.

After SubQuestionPipeline.run_all(), each sub-question has an evidence set. This
module assesses whether that evidence is sufficient to answer it (SUPPORTED),
partially relevant (PARTIALLY_SUPPORTED), absent (UNSUPPORTED), or contradictory
(CONFLICTING).

UNSUPPORTED is handled as a fast path — empty evidence needs no model call.
All non-empty classifications are dispatched concurrently via asyncio.gather,
since sub-question coverage assessments are independent of each other.

The resulting SubQuestionCoverage list drives the iterative retrieval loop in
step 13.5: UNSUPPORTED and PARTIALLY_SUPPORTED trigger another retrieval round,
CONFLICTING stops re-retrieval and surfaces the disagreement in synthesis,
SUPPORTED is already satisfied.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from app.application.queries.sub_question_pipeline import SubQuestionResult
from app.domain.enums import CoverageStatus
from app.domain.ports.coverage import CoverageClassifierPort
from app.domain.retrieval.decomposition import SubQuestion
from app.domain.retrieval.entities import Evidence

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SubQuestionCoverage:
    """A sub-question, its evidence, and how well the evidence covers it."""

    sub_question: SubQuestion
    evidence: Sequence[Evidence]
    coverage: CoverageStatus

    @property
    def needs_another_round(self) -> bool:
        return self.coverage.needs_another_round

    @property
    def is_conflicting(self) -> bool:
        return self.coverage is CoverageStatus.CONFLICTING


class CoverageClassifier:
    """Assess evidence coverage for all sub-questions in a retrieval pass.

    Empty-evidence sub-questions are classified as UNSUPPORTED immediately,
    without calling the model. Non-empty ones are sent to the port in parallel.
    """

    def __init__(self, port: CoverageClassifierPort) -> None:
        self._port = port

    async def classify_all(
        self, results: list[SubQuestionResult]
    ) -> list[SubQuestionCoverage]:
        """Return one SubQuestionCoverage per result, in the same order.

        Sub-questions with no evidence are classified without a model call.
        All others are classified concurrently.
        """
        needs_classification: list[tuple[int, SubQuestionResult]] = []
        fast_path: dict[int, CoverageStatus] = {}

        for i, result in enumerate(results):
            if not list(result.evidence):
                fast_path[i] = CoverageStatus.UNSUPPORTED
                _log.debug(
                    "coverage.fast_path_unsupported",
                    sub_question_id=result.sub_question.id,
                )
            else:
                needs_classification.append((i, result))

        # Concurrent classification for all sub-questions that have evidence.
        if needs_classification:
            classified = await asyncio.gather(
                *[self._classify_one(r) for _, r in needs_classification]
            )
            classified_statuses = {
                idx: status
                for (idx, _), status in zip(needs_classification, classified, strict=True)
            }
        else:
            classified_statuses = {}

        coverages: list[SubQuestionCoverage] = []
        for i, result in enumerate(results):
            status = fast_path.get(i) or classified_statuses[i]
            _log.debug(
                "coverage.classified",
                sub_question_id=result.sub_question.id,
                coverage=status.value,
            )
            coverages.append(
                SubQuestionCoverage(
                    sub_question=result.sub_question,
                    evidence=result.evidence,
                    coverage=status,
                )
            )
        return coverages

    async def _classify_one(self, result: SubQuestionResult) -> CoverageStatus:
        return await self._port.classify(
            result.sub_question.text,
            list(result.evidence),
        )
