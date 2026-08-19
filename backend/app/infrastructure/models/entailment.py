"""Ollama-backed semantic entailment adapter.

Calls the model once per (claim, cited passage) pair using the non-streaming
generate() path — the response is a single word, so streaming adds no value.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.enums import ModelTask
from app.domain.models.entities import LabeledPassage, ModelRequest
from app.domain.models.generation import Claim
from app.domain.models.validation import (
    ENTAILMENT_PREAMBLE,
    ENTAILMENT_SCHEMA,
    EntailmentResult,
    parse_entailment_status,
)
from app.domain.ports.model_gateway import ModelGatewayPort

_TASK_INSTRUCTIONS = (
    "Read the claim and the passage below, then judge whether the passage supports, "
    "contradicts, or does not address the claim."
)


class OllamaClaimEntailment:
    """Check entailment for one claim against each of its cited passages.

    Calls the model once per passage. Each call builds a minimal ModelRequest
    containing only the claim and the single passage under review — no history,
    no evidence slots, no memory — so the model cannot conflate passages or draw
    on context that is irrelevant to this specific (claim, passage) pair.
    """

    def __init__(self, gateway: ModelGatewayPort) -> None:
        self._gateway = gateway

    async def check_claim(
        self,
        claim: Claim,
        passages: Sequence[LabeledPassage],
    ) -> tuple[EntailmentResult, ...]:
        results: list[EntailmentResult] = []
        for passage in passages:
            query = (
                f"Claim: {claim.text}\n"
                f"Passage {passage.label}: {passage.text.value}"
            )
            request = ModelRequest(
                model_task=ModelTask.FAITHFULNESS_CHECK,
                system_preamble=ENTAILMENT_PREAMBLE,
                safety_rules=(),
                task_instructions=_TASK_INSTRUCTIONS,
                query=query,
                output_schema=ENTAILMENT_SCHEMA,
                max_tokens=10,
            )
            response = await self._gateway.generate(request)
            status = parse_entailment_status(response.content.value)
            results.append(
                EntailmentResult(
                    claim=claim,
                    passage_label=passage.label,
                    status=status,
                )
            )
        return tuple(results)
