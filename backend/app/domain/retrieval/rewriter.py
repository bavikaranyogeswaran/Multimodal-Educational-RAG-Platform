"""Query rewriter — make follow-up questions self-contained.

Rule-first: heuristics check for anaphora, back-references, and bare
interrogatives that signal dependence on prior context. Only when a signal
fires is the model called, so simple, independent queries incur no latency.

Returns a (standalone_query, was_rewritten) pair so the caller knows whether
the text changed and can record the rewrite for observability.
"""

from __future__ import annotations

import re

from app.domain.enums import ModelTask
from app.domain.models.entities import ConversationTurn, ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort

_SYSTEM_PREAMBLE = (
    "You are a query rewriting assistant. "
    "You make follow-up student questions self-contained by incorporating "
    "the necessary context from the conversation history."
)

_TASK_INSTRUCTIONS = (
    "Rewrite the student's follow-up question as a complete, standalone "
    "question that can be understood without the conversation history. "
    "Preserve the original meaning exactly. "
    "Output only the rewritten question, with no explanation or preamble."
)

_MAX_TOKENS = 100

# Each pattern is a distinct follow-up signal. Order does not matter — all are
# checked and the first match is sufficient to escalate to the model.
_FOLLOW_UP_SIGNALS: list[re.Pattern[str]] = [
    # Anaphoric opening: starts with a pronoun or demonstrative pointing back
    re.compile(
        r"^(?:it|this|that|they|these|those|its|their|them|the\s+same|the\s+above|the\s+previous)\b",
        re.IGNORECASE,
    ),
    # Bare interrogative — a hanging question word with nothing after it
    re.compile(r"^(?:why|how|when|who|which|what)\s*\?+\s*$", re.IGNORECASE),
    # Explicit back-reference phrases
    re.compile(r"\bas\s+(?:mentioned|described|stated|explained|noted|discussed)\b", re.IGNORECASE),
    re.compile(r"\byou\s+(?:mentioned|said|described|explained|noted|discussed)\b", re.IGNORECASE),
    re.compile(r"\btell\s+me\s+more\b", re.IGNORECASE),
    re.compile(r"\bcan\s+you\s+elaborate\b", re.IGNORECASE),
    re.compile(r"\bexplain\s+(?:it|that|this|them)\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+does\s+(?:it|that|this)\s+mean\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+about\s+(?:it|that|this)\b", re.IGNORECASE),
    # Continuation openings
    re.compile(r"^(?:and|but|so)\s+(?:what|how|why|where|when)\b", re.IGNORECASE),
]


def _is_follow_up(query: str) -> bool:
    return any(p.search(query) for p in _FOLLOW_UP_SIGNALS)


class QueryRewriter:
    """Rewrite follow-up questions into standalone queries using rule+model cascade.

    The heuristic pass is cheap and synchronous. The model is only called when
    the query carries a clear back-reference signal that the heuristic catches.
    Independent questions pass straight through — (original_query, False).
    """

    def __init__(self, gateway: ModelGatewayPort) -> None:
        self._gateway = gateway

    async def rewrite(
        self,
        query: str,
        history: tuple[ConversationTurn, ...],
    ) -> tuple[str, bool]:
        if not history or not _is_follow_up(query):
            return query, False

        request = ModelRequest(
            model_task=ModelTask.QUERY_REWRITE,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS,
            evidence=(),
            conversation_history=history,
            query=query,
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
        )

        response = await self._gateway.generate(request)
        return response.content.value.strip(), True
