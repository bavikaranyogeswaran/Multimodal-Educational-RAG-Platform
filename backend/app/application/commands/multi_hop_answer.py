"""Use case: answer a multi-hop query through decomposition, iterative retrieval,
evidence selection, and hierarchical synthesis.

This use case handles queries whose class requires sub-question decomposition
(MULTI_HOP, MULTI_DOCUMENT, AGGREGATION, COMPARISON). It is used by AnswerUseCase
when the query class is detected; single-turn queries continue through the existing
path unchanged.

Pipeline
--------
1. Decompose the original query into a DecompositionPlan.
2. Run IterativeRetrievalLoop — retrieves evidence per sub-question for up to
   max_rounds, re-running unsatisfied sub-questions against a narrowed document set.
3. EvidenceSelector — deduplicate and cap evidence per sub-question, prioritised
   by coverage status so the best-supported sub-questions get first pick.
4. HierarchicalSynthesizer — two-stage synthesis: answer each sub-question with
   its evidence (concurrently), then combine into a final answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.application.commands.decompose import DecomposeQueryCommand, DecomposeQueryUseCase
from app.application.queries.evidence_selector import EvidenceSelector
from app.application.queries.hierarchical_synthesis import HierarchicalSynthesizer, MultiHopAnswer
from app.application.queries.iterative_retrieval import IterativeRetrievalLoop
from app.domain.models.entities import ConversationTurn
from app.domain.retrieval.entities import RetrievalFilters
from app.domain.scope import ScopeContext


@dataclass(frozen=True)
class MultiHopAnswerCommand:
    """Input to the multi-hop answer use case.

    `history` is the prior conversation turns, forwarded in case the decomposer
    or synthesizer needs them to make the query self-contained.
    `filters` narrow the retrieval scope (e.g. to a specific document or chapter).
    """

    scope: ScopeContext
    query: str
    history: tuple[ConversationTurn, ...] = ()
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)


class MultiHopAnswerUseCase:
    """Orchestrate the full multi-hop pipeline for one query.

    Each dependency handles one well-defined stage; this use case only threads
    the outputs of one stage into the inputs of the next.
    """

    def __init__(
        self,
        *,
        decompose: DecomposeQueryUseCase,
        loop: IterativeRetrievalLoop,
        selector: EvidenceSelector,
        synthesizer: HierarchicalSynthesizer,
    ) -> None:
        self._decompose = decompose
        self._loop = loop
        self._selector = selector
        self._synthesizer = synthesizer

    async def execute(self, command: MultiHopAnswerCommand) -> MultiHopAnswer:
        """Run the four-stage pipeline and return the synthesized answer."""
        plan = await self._decompose.execute(
            DecomposeQueryCommand(query=command.query, scope=command.scope)
        )

        ir_result = await self._loop.run(
            plan,
            command.scope,
            filters=command.filters if command.filters.document_ids else None,
        )

        selected = self._selector.select(ir_result.coverages)

        return await self._synthesizer.synthesize(command.query, selected)
