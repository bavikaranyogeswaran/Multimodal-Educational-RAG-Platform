"""LLM-backed coverage classification adapter."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.enums import CoverageStatus, ModelTask
from app.domain.errors import DomainError
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.retrieval.entities import Evidence

_SYSTEM_PREAMBLE = (
    "You assess whether a set of retrieved passages is sufficient to answer a question. "
    "You respond with exactly one word from the allowed set."
)

_TASK_INSTRUCTIONS = """\
Question: {question}

Retrieved passages:
{passages}

Does the evidence above answer the question? Respond with exactly one word:
- SUPPORTED — the passages clearly and completely answer the question
- PARTIALLY_SUPPORTED — the passages are relevant but leave gaps or only address part of the question
- UNSUPPORTED — the passages do not address the question at all
- CONFLICTING — two or more passages make incompatible claims about the same fact

Respond with exactly one word only."""

_VALID = {s.value for s in CoverageStatus}


class LlmCoverageClassifier:
    """Calls the configured model gateway to classify evidence coverage."""

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def classify(
        self,
        question: str,
        evidence: Sequence[Evidence],
    ) -> CoverageStatus:
        passages = "\n\n".join(
            f"[{ev.label}] {ev.chunk.text.value}" for ev in evidence
        )
        request = ModelRequest(
            model_task=ModelTask.FAITHFULNESS_CHECK,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS.format(
                question=question, passages=passages
            ),
            query=question,
            max_tokens=10,
            temperature=0.0,
        )
        response = await self._gateway.generate(request)
        return _parse(response.content.value)


def _parse(raw: str) -> CoverageStatus:
    word = raw.strip().upper()
    if word in _VALID:
        return CoverageStatus(word)
    # Tolerate minor variations (e.g. "PARTIALLY SUPPORTED" with a space)
    normalised = word.replace(" ", "_")
    if normalised in _VALID:
        return CoverageStatus(normalised)
    raise DomainError(
        f"coverage classification returned unexpected value {raw!r}; "
        f"expected one of {sorted(_VALID)}"
    )
