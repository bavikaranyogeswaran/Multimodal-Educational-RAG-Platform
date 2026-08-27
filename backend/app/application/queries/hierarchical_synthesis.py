"""Two-stage hierarchical synthesis for multi-hop queries.

After EvidenceSelector produces a deduplicated evidence set per sub-question,
HierarchicalSynthesizer drives two passes through the model:

  Pass 1 — run all sub-questions concurrently, each answered with its own
            evidence. Concurrency is safe here because sub-question answers
            are independent — no sub-question reads another's evidence.

  Pass 2 — synthesize the original query from the ordered sub-answers produced
            in Pass 1. The model sees the full chain of reasoning rather than
            every raw passage at once, which keeps the context focused and lets
            it draw cross-document connections explicitly.

The result, MultiHopAnswer, carries both the final answer text and the
individual sub-answers so callers can surface them for transparency or
debugging.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from app.application.queries.evidence_selector import SubQuestionEvidence
from app.domain.ports.multi_hop import MultiHopSynthesisPort, SubAnswerItem

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class MultiHopAnswer:
    """Final synthesized answer and the per-sub-question answers that built it."""

    answer: str
    sub_answers: tuple[SubAnswerItem, ...]


class HierarchicalSynthesizer:
    """Orchestrate two-stage synthesis for a multi-hop retrieval result.

    Pass 1 answers each sub-question concurrently; Pass 2 combines them.
    The synthesizer is stateless — the port carries all model-specific state.
    """

    def __init__(self, port: MultiHopSynthesisPort) -> None:
        self._port = port

    async def synthesize(
        self,
        original_query: str,
        sub_evidences: list[SubQuestionEvidence],
    ) -> MultiHopAnswer:
        """Run both synthesis passes and return the combined answer.

        Sub-answers are in the same order as `sub_evidences` regardless of
        how the concurrent Pass 1 tasks finish.
        """
        _log.info(
            "hierarchical_synthesis.start",
            sub_questions=len(sub_evidences),
        )

        # Pass 1 — concurrent; asyncio.gather preserves order.
        sub_answers: tuple[SubAnswerItem, ...] = tuple(
            await asyncio.gather(
                *[self._answer_one(se) for se in sub_evidences]
            )
        )

        _log.debug(
            "hierarchical_synthesis.pass1_complete",
            count=len(sub_answers),
        )

        # Pass 2 — single call combining all sub-answers.
        final = await self._port.synthesize_final(original_query, sub_answers)

        _log.info("hierarchical_synthesis.complete")

        return MultiHopAnswer(answer=final, sub_answers=sub_answers)

    async def _answer_one(self, se: SubQuestionEvidence) -> SubAnswerItem:
        answer = await self._port.synthesize_sub_answer(
            se.sub_question.text,
            list(se.evidence),
            se.coverage,
        )
        _log.debug(
            "hierarchical_synthesis.sub_answer",
            sub_question_id=se.sub_question.id,
            coverage=se.coverage.value,
        )
        return SubAnswerItem(
            sub_question=se.sub_question.text,
            answer=answer,
            coverage=se.coverage,
        )
