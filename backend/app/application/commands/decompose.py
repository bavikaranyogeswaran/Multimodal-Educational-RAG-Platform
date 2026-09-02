"""Use case: decompose a complex multi-hop query into ordered sub-questions.

Triggered by answer.py when the query class calls for decomposition
(MULTI_DOCUMENT, MULTI_HOP, AGGREGATION, COMPARISON). Each returned sub-question
maps to one full retrieval pipeline run in the Phase 13 multi-hop path.

The port asks the LLM; this use case enforces the structural constraints the port
cannot: unique IDs, no dangling references, no cycles, and the hard cap on the
number of sub-questions.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.domain.ports.adapters import QueryDecompositionPort
from app.domain.retrieval.decomposition import DecompositionPlan
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)

_MAX_SUB_QUESTIONS = 8


@dataclass(frozen=True)
class DecomposeQueryCommand:
    query: str
    scope: ScopeContext


class DecomposeQueryUseCase:
    """Break a complex query into topologically ordered sub-questions.

    If the decomposition port returns more sub-questions than the hard cap allows,
    the excess is silently discarded and a warning is logged. The caller gets a
    plan that satisfies the cap; the log entry lets the prompt be tuned later.
    """

    def __init__(self, decomposition_port: QueryDecompositionPort) -> None:
        self._port = decomposition_port

    async def execute(self, command: DecomposeQueryCommand) -> DecompositionPlan:
        raw = await self._port.decompose(
            command.query,
            max_sub_questions=_MAX_SUB_QUESTIONS,
        )

        if len(raw) > _MAX_SUB_QUESTIONS:
            _log.warning(
                "decompose.cap_exceeded",
                returned=len(raw),
                cap=_MAX_SUB_QUESTIONS,
            )
            raw = raw[:_MAX_SUB_QUESTIONS]

        return DecompositionPlan.build(command.query, raw)
