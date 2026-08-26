"""Tests for DecomposeQueryUseCase."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.application.commands.decompose import DecomposeQueryCommand, DecomposeQueryUseCase
from app.domain.errors import DecompositionError, InvariantViolationError
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion
from app.domain.scope import ScopeContext


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _port(*, returns: list[SubQuestion]) -> AsyncMock:
    port = AsyncMock()
    port.decompose = AsyncMock(return_value=returns)
    return port


class TestDecomposeQueryUseCase:
    async def test_returns_plan_for_simple_decomposition(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="What is Newton's first law?"),
            SubQuestion(id="Q2", text="What is Newton's second law?"),
        ]
        use_case = DecomposeQueryUseCase(_port(returns=sqs))
        plan = await use_case.execute(
            DecomposeQueryCommand(query="Explain Newton's laws of motion", scope=_scope())
        )
        assert isinstance(plan, DecompositionPlan)
        assert plan.original_query == "Explain Newton's laws of motion"
        assert len(plan) == 2

    async def test_passes_query_to_port(self) -> None:
        port = _port(returns=[SubQuestion(id="Q1", text="Q?")])
        use_case = DecomposeQueryUseCase(port)
        await use_case.execute(DecomposeQueryCommand(query="my query", scope=_scope()))
        args, _ = port.decompose.call_args
        assert args[0] == "my query"

    async def test_passes_max_sub_questions_to_port(self) -> None:
        port = _port(returns=[SubQuestion(id="Q1", text="Q?")])
        use_case = DecomposeQueryUseCase(port)
        await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))
        _, kwargs = port.decompose.call_args
        assert kwargs["max_sub_questions"] == 8

    async def test_caps_at_eight_when_port_returns_more(self) -> None:
        sqs = [SubQuestion(id=f"Q{i}", text=f"Question {i}?") for i in range(1, 11)]
        use_case = DecomposeQueryUseCase(_port(returns=sqs))
        plan = await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))
        assert len(plan) == 8

    async def test_exactly_eight_sub_questions_not_capped(self) -> None:
        sqs = [SubQuestion(id=f"Q{i}", text=f"Question {i}?") for i in range(1, 9)]
        use_case = DecomposeQueryUseCase(_port(returns=sqs))
        plan = await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))
        assert len(plan) == 8

    async def test_single_sub_question(self) -> None:
        sq = SubQuestion(id="Q1", text="The only question?")
        use_case = DecomposeQueryUseCase(_port(returns=[sq]))
        plan = await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))
        assert len(plan) == 1
        assert plan.sub_questions[0].id == "Q1"

    async def test_topological_order_preserved(self) -> None:
        # Port returns Q2 before Q1, but Q2 depends on Q1
        sqs = [
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"})),
            SubQuestion(id="Q1", text="First?"),
        ]
        use_case = DecomposeQueryUseCase(_port(returns=sqs))
        plan = await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))
        ids = [sq.id for sq in plan]
        assert ids.index("Q1") < ids.index("Q2")

    async def test_decomposition_error_propagates(self) -> None:
        port = AsyncMock()
        port.decompose = AsyncMock(side_effect=DecompositionError("model refused"))
        use_case = DecomposeQueryUseCase(port)
        with pytest.raises(DecompositionError):
            await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))

    async def test_cycle_in_port_output_raises_invariant_error(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="First?", depends_on=frozenset({"Q2"})),
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"})),
        ]
        use_case = DecomposeQueryUseCase(_port(returns=sqs))
        with pytest.raises(InvariantViolationError, match="cycle"):
            await use_case.execute(DecomposeQueryCommand(query="q", scope=_scope()))
