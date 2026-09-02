"""LLM-backed two-stage hierarchical synthesis adapter."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.enums import CoverageStatus, ModelTask
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.ports.multi_hop import SubAnswerItem
from app.domain.retrieval.entities import Evidence

_SYSTEM_PREAMBLE = (
    "You are a knowledgeable tutor answering questions for a student. "
    "You answer accurately based on the provided material, "
    "acknowledge gaps where the evidence is partial or absent, "
    "and surface conflicts where sources disagree."
)

_SUB_ANSWER_INSTRUCTIONS = """\
Answer the sub-question below using only the retrieved passages.

Coverage assessment: {coverage}
{coverage_note}
Retrieved passages:
{passages}

Sub-question: {sub_question}

Write a concise, accurate answer grounded in the passages above. \
If coverage is PARTIALLY_SUPPORTED, note what is missing. \
If coverage is CONFLICTING, describe the disagreement. \
If coverage is UNSUPPORTED, say so clearly rather than guessing."""

_COVERAGE_NOTES = {
    CoverageStatus.SUPPORTED: "",
    CoverageStatus.PARTIALLY_SUPPORTED: (
        "The passages only partially address this question — acknowledge any gaps.\n"
    ),
    CoverageStatus.UNSUPPORTED: (
        "The passages do not address this question — state clearly that the material "
        "does not cover it.\n"
    ),
    CoverageStatus.CONFLICTING: (
        "The passages contain conflicting information — describe the disagreement "
        "rather than picking one side.\n"
    ),
}

_FINAL_ANSWER_INSTRUCTIONS = """\
Using the sub-answers below, write a single coherent response to the original question.

Sub-answers (in order):
{sub_answers}

Original question: {original_query}

Synthesize the sub-answers into one clear, well-structured response. \
Do not repeat information unnecessarily. \
Preserve any caveats about partial coverage or conflicts from the sub-answers."""


class LlmMultiHopSynthesis:
    """Calls the configured model gateway for two-stage multi-hop synthesis."""

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def synthesize_sub_answer(
        self,
        sub_question: str,
        evidence: Sequence[Evidence],
        coverage: CoverageStatus,
    ) -> str:
        passages = "\n\n".join(
            f"[{ev.label}] {ev.chunk.text.value}" for ev in evidence
        )
        request = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_SUB_ANSWER_INSTRUCTIONS.format(
                coverage=coverage.value,
                coverage_note=_COVERAGE_NOTES.get(coverage, ""),
                passages=passages,
                sub_question=sub_question,
            ),
            query=sub_question,
            max_tokens=512,
            temperature=0.1,
        )
        response = await self._gateway.generate(request)
        return response.content.value.strip()

    async def synthesize_final(
        self,
        original_query: str,
        sub_answers: Sequence[SubAnswerItem],
    ) -> str:
        sub_answers_text = "\n\n".join(
            f"Q: {item.sub_question}\n"
            f"Coverage: {item.coverage.value}\n"
            f"A: {item.answer}"
            for item in sub_answers
        )
        request = ModelRequest(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_FINAL_ANSWER_INSTRUCTIONS.format(
                sub_answers=sub_answers_text,
                original_query=original_query,
            ),
            query=original_query,
            max_tokens=1024,
            temperature=0.1,
        )
        response = await self._gateway.generate(request)
        return response.content.value.strip()
