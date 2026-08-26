"""Port for sub-question coverage classification."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.enums import CoverageStatus
from app.domain.retrieval.entities import Evidence


class CoverageClassifierPort(Protocol):
    """LLM-backed assessment of whether retrieved evidence covers a sub-question.

    The classifier is asked once per sub-question after retrieval. It receives the
    question text and every evidence item retrieved for it, then returns one of the
    four CoverageStatus values:

      SUPPORTED          — the passages clearly answer the question
      PARTIALLY_SUPPORTED — the passages are relevant but leave gaps
      UNSUPPORTED        — the passages do not address the question
      CONFLICTING        — two or more passages make incompatible claims

    The caller is responsible for the UNSUPPORTED fast-path (empty evidence) and
    for batching concurrent calls across sub-questions. This port handles only the
    model interaction for a single (question, evidence) pair.
    """

    async def classify(
        self,
        question: str,
        evidence: Sequence[Evidence],
    ) -> CoverageStatus:
        """Return the coverage status for `question` given `evidence`.

        `evidence` is guaranteed non-empty by the caller (empty evidence is always
        UNSUPPORTED and never reaches this method). The question is the sub-question
        text, not the original query.
        """
        ...
