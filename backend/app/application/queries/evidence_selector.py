"""Coverage-aware evidence selection for multi-hop synthesis.

After the iterative retrieval loop each sub-question has a final coverage
status and an evidence set. This module decides which evidence actually goes
to the synthesis step.

Selection rules
---------------
1. Sub-questions are processed in coverage-priority order — SUPPORTED first,
   then PARTIALLY_SUPPORTED, CONFLICTING, UNSUPPORTED — so the most useful
   evidence gets first claim on shared chunks.
2. Each chunk (identified by chunk.id) is assigned to at most one sub-question.
   When the same chunk appears in multiple sub-questions' evidence, the
   higher-priority sub-question claims it and lower-priority ones see it removed.
3. Each sub-question keeps at most max_per_sub_question evidence items after
   deduplication.
4. Results are returned in the original sub-question order, not priority order,
   so callers can interleave them with the plan structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.application.queries.coverage_classifier import SubQuestionCoverage
from app.domain.enums import CoverageStatus
from app.domain.retrieval.decomposition import SubQuestion
from app.domain.retrieval.entities import Evidence

_log = structlog.get_logger(__name__)

# Lower number = higher priority for evidence claiming.
_COVERAGE_PRIORITY: dict[CoverageStatus, int] = {
    CoverageStatus.SUPPORTED: 0,
    CoverageStatus.PARTIALLY_SUPPORTED: 1,
    CoverageStatus.CONFLICTING: 2,
    CoverageStatus.UNSUPPORTED: 3,
}


@dataclass(frozen=True, slots=True)
class SubQuestionEvidence:
    """Evidence assigned to one sub-question after deduplication and capping.

    This is the unit that the synthesis step operates on: each sub-question's
    text, its final coverage status, and the deduplicated evidence that supports
    (or fails to support) an answer to it.
    """

    sub_question: SubQuestion
    evidence: tuple[Evidence, ...]
    coverage: CoverageStatus


class EvidenceSelector:
    """Pick the most valuable, non-redundant evidence for each sub-question.

    Chunks shared across sub-questions are assigned to the sub-question whose
    coverage status is highest, so that synthesis always receives the strongest
    evidence for each claim. The per-sub-question cap keeps context size bounded.
    """

    def __init__(self, max_per_sub_question: int = 5) -> None:
        if max_per_sub_question < 1:
            raise ValueError(
                f"max_per_sub_question must be at least 1, got {max_per_sub_question}"
            )
        self._max = max_per_sub_question

    def select(self, coverages: list[SubQuestionCoverage]) -> list[SubQuestionEvidence]:
        """Deduplicate and cap evidence, returning one entry per sub-question.

        Results are in the same order as `coverages`.
        """
        if not coverages:
            return []

        indexed = list(enumerate(coverages))

        # Claim chunks in priority order (SUPPORTED first).
        priority_order = sorted(indexed, key=lambda ic: _COVERAGE_PRIORITY[ic[1].coverage])

        claimed: set[UUID] = set()
        assigned: dict[int, tuple[Evidence, ...]] = {}

        for idx, cov in priority_order:
            selected: list[Evidence] = []
            for ev in cov.evidence:
                chunk_id: UUID = ev.chunk.id
                if chunk_id not in claimed:
                    claimed.add(chunk_id)
                    selected.append(ev)
                    if len(selected) >= self._max:
                        break
            assigned[idx] = tuple(selected)

            _log.debug(
                "evidence_selector.assigned",
                sub_question_id=cov.sub_question.id,
                coverage=cov.coverage.value,
                assigned=len(assigned[idx]),
                skipped_duplicates=len(list(cov.evidence)) - len(assigned[idx]),
            )

        return [
            SubQuestionEvidence(
                sub_question=cov.sub_question,
                evidence=assigned[idx],
                coverage=cov.coverage,
            )
            for idx, cov in indexed
        ]
