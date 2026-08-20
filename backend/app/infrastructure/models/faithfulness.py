"""Ollama-backed answer faithfulness adapter.

One non-streaming call per answer, comparing the prose against the claims it was built
from. The response is a single word, so streaming would add nothing.
"""

from __future__ import annotations

from app.domain.enums import AnswerFidelity, ModelTask
from app.domain.models.entities import ModelRequest
from app.domain.models.generation import GeneratedAnswer
from app.domain.models.validation import (
    FIDELITY_PREAMBLE,
    FIDELITY_SCHEMA,
    build_fidelity_query,
    parse_fidelity,
)
from app.domain.ports.model_gateway import ModelGatewayPort

_TASK_INSTRUCTIONS = (
    "Read the answer and the claims below, then judge whether the answer states any "
    "fact that none of the claims covers."
)


class OllamaAnswerFaithfulness:
    """Compare an answer against its own claims in a single model call.

    The request carries only the answer and its claims — no evidence, no history, no
    memory. Everything else is a reason to judge the prose generously: a passage in
    context invites the model to find support the claims never made, which is the exact
    failure this check exists to catch.
    """

    def __init__(self, gateway: ModelGatewayPort) -> None:
        self._gateway = gateway

    async def check_answer(self, answer: GeneratedAnswer) -> AnswerFidelity:
        # No claims means nothing to overstate against. An abstaining answer never
        # reaches here — the decision short-circuits before the check is called — but a
        # model call that could only ever return one value is worth not making.
        if not answer.claims:
            return AnswerFidelity.FAITHFUL

        request = ModelRequest(
            model_task=ModelTask.FAITHFULNESS_CHECK,
            system_preamble=FIDELITY_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS,
            query=build_fidelity_query(answer),
            output_schema=FIDELITY_SCHEMA,
            max_tokens=10,
        )
        response = await self._gateway.generate(request)
        return parse_fidelity(response.content.value)
