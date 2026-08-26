"""Tests for SubQuestion and DecompositionPlan domain entities."""

from __future__ import annotations

import pytest

from app.domain.errors import InvariantViolationError
from app.domain.retrieval.decomposition import DecompositionPlan, SubQuestion


class TestSubQuestion:
    def test_constructs_with_valid_data(self) -> None:
        sq = SubQuestion(id="Q1", text="What is Newton's first law?")
        assert sq.id == "Q1"
        assert sq.text == "What is Newton's first law?"
        assert sq.depends_on == frozenset()

    def test_constructs_with_dependencies(self) -> None:
        sq = SubQuestion(id="Q2", text="How does it compare?", depends_on=frozenset({"Q1"}))
        assert sq.depends_on == frozenset({"Q1"})

    def test_blank_id_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="id"):
            SubQuestion(id="  ", text="Some question?")

    def test_empty_id_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="id"):
            SubQuestion(id="", text="Some question?")

    def test_blank_text_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="text"):
            SubQuestion(id="Q1", text="   ")

    def test_self_dependency_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="cannot depend on itself"):
            SubQuestion(id="Q1", text="Question?", depends_on=frozenset({"Q1"}))


class TestDecompositionPlanBuild:
    def test_single_sub_question(self) -> None:
        sq = SubQuestion(id="Q1", text="What is gravity?")
        plan = DecompositionPlan.build("What is gravity?", [sq])
        assert len(plan) == 1
        assert plan.sub_questions[0].id == "Q1"

    def test_original_query_preserved(self) -> None:
        sq = SubQuestion(id="Q1", text="sub")
        plan = DecompositionPlan.build("original query", [sq])
        assert plan.original_query == "original query"

    def test_empty_list_raises(self) -> None:
        with pytest.raises(InvariantViolationError, match="at least one"):
            DecompositionPlan.build("query", [])

    def test_blank_original_query_raises(self) -> None:
        sq = SubQuestion(id="Q1", text="sub")
        with pytest.raises(InvariantViolationError, match="original_query"):
            DecompositionPlan.build("  ", [sq])

    def test_duplicate_ids_raise(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="First question?"),
            SubQuestion(id="Q1", text="Duplicate id?"),
        ]
        with pytest.raises(InvariantViolationError, match="unique"):
            DecompositionPlan.build("query", sqs)

    def test_dangling_depends_on_raises(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="First?"),
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q99"})),
        ]
        with pytest.raises(InvariantViolationError, match="unknown id"):
            DecompositionPlan.build("query", sqs)

    def test_two_node_cycle_raises(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="First?", depends_on=frozenset({"Q2"})),
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"})),
        ]
        with pytest.raises(InvariantViolationError, match="cycle"):
            DecompositionPlan.build("query", sqs)

    def test_three_node_cycle_raises(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="First?", depends_on=frozenset({"Q3"})),
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"})),
            SubQuestion(id="Q3", text="Third?", depends_on=frozenset({"Q2"})),
        ]
        with pytest.raises(InvariantViolationError, match="cycle"):
            DecompositionPlan.build("query", sqs)

    def test_topological_order_dependency_before_dependent(self) -> None:
        sqs = [
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"})),
            SubQuestion(id="Q1", text="First?"),
        ]
        plan = DecompositionPlan.build("query", sqs)
        ids = [sq.id for sq in plan.sub_questions]
        assert ids.index("Q1") < ids.index("Q2")

    def test_chain_topological_order(self) -> None:
        sqs = [
            SubQuestion(id="Q3", text="Third?", depends_on=frozenset({"Q2"})),
            SubQuestion(id="Q2", text="Second?", depends_on=frozenset({"Q1"})),
            SubQuestion(id="Q1", text="First?"),
        ]
        plan = DecompositionPlan.build("query", sqs)
        ids = [sq.id for sq in plan.sub_questions]
        assert ids == ["Q1", "Q2", "Q3"]

    def test_diamond_topological_order(self) -> None:
        # Q4 depends on Q2 and Q3; Q3 depends on Q1; Q1 and Q2 are independent
        sqs = [
            SubQuestion(id="Q4", text="Fourth?", depends_on=frozenset({"Q2", "Q3"})),
            SubQuestion(id="Q3", text="Third?", depends_on=frozenset({"Q1"})),
            SubQuestion(id="Q2", text="Second?"),
            SubQuestion(id="Q1", text="First?"),
        ]
        plan = DecompositionPlan.build("query", sqs)
        ids = [sq.id for sq in plan.sub_questions]
        assert ids.index("Q1") < ids.index("Q3")
        assert ids.index("Q2") < ids.index("Q4")
        assert ids.index("Q3") < ids.index("Q4")

    def test_independent_sub_questions_all_present(self) -> None:
        sqs = [
            SubQuestion(id="Q1", text="First?"),
            SubQuestion(id="Q2", text="Second?"),
            SubQuestion(id="Q3", text="Third?"),
        ]
        plan = DecompositionPlan.build("query", sqs)
        assert len(plan) == 3

    def test_iterable(self) -> None:
        sq = SubQuestion(id="Q1", text="First?")
        plan = DecompositionPlan.build("query", [sq])
        assert list(plan) == [sq]
