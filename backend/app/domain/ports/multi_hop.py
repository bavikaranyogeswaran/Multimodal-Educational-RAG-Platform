"""Port for two-stage hierarchical synthesis of multi-hop answers.

Single-turn retrieval produces one flat evidence set that the answer use case
sends to the model in a single prompt. Multi-hop retrieval produces per-sub-
question evidence sets that need two synthesis passes:

  Pass 1 — sub-question answering:
    Each sub-question is answered independently using only its own evidence.
    Sub-questions are answered concurrently (they are independent at this stage).
    The coverage status is forwarded so the model can appropriately qualify
    answers for PARTIALLY_SUPPORTED or CONFLICTING sub-questions.

  Pass 2 — final synthesis:
    The original query and all sub-answers are combined into a single coherent
    response. The model can draw on the sub-answers to reason across documents
    without needing to re-read every passage at once.

Implementations are responsible for prompt assembly, token budget, and the
output format contract for each call. The caller handles concurrency for Pass 1
and ordering of sub_answers in Pass 2.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.enums import CoverageStatus
from app.domain.retrieval.entities import Evidence


@dataclass(frozen=True, slots=True)
class SubAnswerItem:
    """One sub-question and the answer produced for it in Pass 1.

    `coverage` travels with the sub-answer so the Pass 2 model can qualify
    its synthesized response appropriately — e.g. surfacing a known conflict
    or noting a gap the material did not address.
    """

    sub_question: str
    answer: str
    coverage: CoverageStatus


class MultiHopSynthesisPort(Protocol):
    """LLM-backed two-stage synthesis for multi-hop queries.

    An implementation must remain stateless between calls — two concurrent
    callers must not interfere with each other's context.
    """

    async def synthesize_sub_answer(
        self,
        sub_question: str,
        evidence: Sequence[Evidence],
        coverage: CoverageStatus,
    ) -> str:
        """Produce a brief answer to one sub-question from its evidence.

        `coverage` indicates how well the evidence addresses the sub-question.
        The model should acknowledge gaps (PARTIALLY_SUPPORTED, UNSUPPORTED)
        or conflicts (CONFLICTING) rather than fabricating certainty.
        """
        ...

    async def synthesize_final(
        self,
        original_query: str,
        sub_answers: Sequence[SubAnswerItem],
    ) -> str:
        """Combine all sub-answers into a single response to the original query.

        `sub_answers` is ordered in the same way as the decomposition plan —
        dependencies appear before the sub-questions that depend on them.
        The model should weave them into a coherent, non-repetitive answer.
        """
        ...
