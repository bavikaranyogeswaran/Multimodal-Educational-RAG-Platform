"""Query expansion — generate 2–3 paraphrases of the student's question.

Expansion broadens the vocabulary surface for retrieval without changing the
information need. Only queries whose RetrievalPlan allows it are expanded;
exact-term and selected-object queries must stay as written.
"""

from __future__ import annotations

import re

from app.domain.enums import ModelTask
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.retrieval.entities import RetrievalPlan

_SYSTEM_PREAMBLE = (
    "You are a search query assistant that helps improve document retrieval "
    "by rephrasing student questions with different vocabulary."
)

_TASK_INSTRUCTIONS = (
    "Generate 2 to 3 alternative phrasings of the student's question that "
    "express the same information need using different vocabulary or sentence "
    "structure. Output only the alternative queries, one per line, with no "
    "numbering, bullet points, labels, or explanations."
)

_MAX_TOKENS = 150
_MAX_VARIANTS = 3

# Strips leading list markers: "1. ", "2) ", "- ", "* ", "• "
_MARKER = re.compile(r"^\s*(?:\d+[.)]\s*|[-*•]\s*)")


def _parse_variants(text: str) -> list[str]:
    lines = [_MARKER.sub("", line).strip() for line in text.splitlines()]
    return [line for line in lines if line][:_MAX_VARIANTS]


class QueryExpander:
    """Expand a query into 2–3 paraphrases via the model, then prepend the original.

    When the plan forbids expansion the model is never called and the original
    query is returned in a single-item list, so the caller needs no branch.
    """

    def __init__(self, gateway: ModelGatewayPort) -> None:
        self._gateway = gateway

    async def expand(self, query: str, plan: RetrievalPlan) -> list[str]:
        if not plan.expand_queries:
            return [query]

        request = ModelRequest(
            model_task=ModelTask.QUERY_EXPANSION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS,
            evidence=(),
            conversation_history=(),
            query=query,
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
        )

        response = await self._gateway.generate(request)
        variants = _parse_variants(response.content.value)

        # Exclude any variant that duplicates the original — the model sometimes
        # echoes it back verbatim as its first "alternative".
        return [query] + [v for v in variants if v != query]
