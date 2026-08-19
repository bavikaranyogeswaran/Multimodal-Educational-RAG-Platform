"""Tests for ContextBuilder.

Three things are under test. First, that the essentials — system identity, safety rules,
the task, the evidence, the question, and any requirement binding critically — are never
touched, whatever the budget: they are what makes an answer possible rather than merely
better, and shedding them is not this module's decision to make. Second, that everything
else is given up in a fixed order, one slot at a time, stopping as soon as the prompt fits
— never more than necessary, never out of order. Third, that a turn's instructions are
settled and named before any of that happens, so what the budget removes is a requirement
that was actually going to be sent.

Token counting is a word count. Every sheddable slot below costs exactly three words, and
the essentials cost fourteen between them, so a budget can be chosen that forces exactly
one shedding step and no more — which is what most of these tests do, one step at a time.
A requirement renders as its name, its level and its text, so a one-word requirement costs
three words like everything else.
"""

from __future__ import annotations

import pytest

from app.domain.enums import (
    InstructionCategory,
    MessageRole,
    ModelTask,
    RequirementLevel,
)
from app.domain.errors import InvariantViolationError
from app.domain.models.context_builder import ContextBuilder, ContextInputs
from app.domain.models.entities import ConversationTurn, LabeledPassage
from app.domain.models.instructions import Instruction
from app.domain.values import UntrustedText

# Fourteen words between them, and never shed regardless of budget.
_SYSTEM_PREAMBLE = "system preamble"  # 2
_SAFETY_RULES = ("safety rule here",)  # 3
_TASK_INSTRUCTIONS = "task instructions text"  # 3
_QUERY = "the question asked"  # 3
_CRITICAL_INSTRUCTION = Instruction(  # renders as "R1 [CRITICAL] Ground." — 3
    text="Ground.",
    category=InstructionCategory.GROUNDING_AND_SOURCE_USE,
    level=RequirementLevel.CRITICAL,
)
_ESSENTIALS_COST = 14

# Every sheddable slot costs exactly three words, so each shedding step reduces the total
# by exactly three and the budgets below can be chosen exactly.
_CRITICAL_CHECKLIST = ("checklist point here",)
_OUTPUT_SCHEMA = "schema text here"
_PREFERRED_INSTRUCTION = Instruction(
    text="Brief.",
    category=InstructionCategory.USER_CONSTRAINT,
    level=RequirementLevel.PREFERRED,
)
_KNOWLEDGE_BASE_STATE = "kb state text"
_ROLLING_SUMMARY = "rolling summary text"
_RELEVANT_MEMORY = ("relevant fact here",)
_PINNED_MEMORY = ("pinned fact here",)
_CONVERSATION_HISTORY = (
    ConversationTurn(role=MessageRole.USER, content=UntrustedText("turn text here")),
)
_REQUIRED_INSTRUCTION = Instruction(
    text="Cite.",
    category=InstructionCategory.STYLE_PREFERENCE,
    level=RequirementLevel.REQUIRED,
)

# Declared out of category order, so every test also proves the builder does the sorting.
_INSTRUCTIONS = (_REQUIRED_INSTRUCTION, _PREFERRED_INSTRUCTION, _CRITICAL_INSTRUCTION)

_PER_SLOT_COST = 3
_SHEDDABLE_SLOT_COUNT = 9
_FULL_COST = _ESSENTIALS_COST + _SHEDDABLE_SLOT_COUNT * _PER_SLOT_COST


def _count_words(text: str) -> int:
    return len(text.split())


def _builder(*, budget: int) -> ContextBuilder:
    return ContextBuilder(_count_words, token_budget=budget)


def _full_inputs(**overrides: object) -> ContextInputs:
    defaults: dict[str, object] = {
        "model_task": ModelTask.ANSWER_GENERATION,
        "system_preamble": _SYSTEM_PREAMBLE,
        "safety_rules": _SAFETY_RULES,
        "task_instructions": _TASK_INSTRUCTIONS,
        "query": _QUERY,
        "instructions": _INSTRUCTIONS,
        "knowledge_base_state": _KNOWLEDGE_BASE_STATE,
        "pinned_memory": _PINNED_MEMORY,
        "relevant_memory": _RELEVANT_MEMORY,
        "rolling_summary": _ROLLING_SUMMARY,
        "conversation_history": _CONVERSATION_HISTORY,
        "critical_checklist": _CRITICAL_CHECKLIST,
        "output_schema": _OUTPUT_SCHEMA,
    }
    return ContextInputs(**{**defaults, **overrides})  # type: ignore[arg-type]


def _budget_after(steps_shed: int) -> int:
    """The exact budget that forces `steps_shed` slots to be cleared and no more."""
    return _ESSENTIALS_COST + (_SHEDDABLE_SLOT_COUNT - steps_shed) * _PER_SLOT_COST


def _instructions_of(request: object) -> list[Instruction]:
    requirements = request.mandatory_requirements  # type: ignore[attr-defined]
    return [requirement.instruction for requirement in requirements]


# ---------------------------------------------------------------------------
# Nothing shed when everything fits
# ---------------------------------------------------------------------------


class TestNothingSheddable:
    def test_a_prompt_that_fits_is_returned_whole(self) -> None:
        request = _builder(budget=_FULL_COST).build(_full_inputs())
        assert request.critical_checklist == _CRITICAL_CHECKLIST
        assert request.output_schema == _OUTPUT_SCHEMA
        assert _instructions_of(request) == [
            _CRITICAL_INSTRUCTION,
            _PREFERRED_INSTRUCTION,
            _REQUIRED_INSTRUCTION,
        ]
        assert request.knowledge_base_state == _KNOWLEDGE_BASE_STATE
        assert request.rolling_summary == _ROLLING_SUMMARY
        assert request.relevant_memory == _RELEVANT_MEMORY
        assert request.pinned_memory == _PINNED_MEMORY
        assert request.conversation_history == _CONVERSATION_HISTORY

    def test_a_generous_budget_changes_nothing(self) -> None:
        request = _builder(budget=_FULL_COST * 10).build(_full_inputs())
        assert request.conversation_history == _CONVERSATION_HISTORY


# ---------------------------------------------------------------------------
# The shedding order, one slot at a time
# ---------------------------------------------------------------------------


class TestSheddingOrder:
    def test_the_checklist_is_shed_first(self) -> None:
        request = _builder(budget=_budget_after(1)).build(_full_inputs())
        assert request.critical_checklist == ()
        assert request.output_schema == _OUTPUT_SCHEMA

    def test_the_checklist_alone_is_not_shed_before_it_has_to_be(self) -> None:
        """One token of headroom above the checklist's cost is enough to keep it."""
        request = _builder(budget=_FULL_COST).build(_full_inputs())
        assert request.critical_checklist == _CRITICAL_CHECKLIST

    def test_the_output_schema_goes_next(self) -> None:
        request = _builder(budget=_budget_after(2)).build(_full_inputs())
        assert request.critical_checklist == ()
        assert request.output_schema is None
        assert _PREFERRED_INSTRUCTION in _instructions_of(request)

    def test_preferred_requirements_go_next(self) -> None:
        """A preference unmet makes the answer less pleasant to read; everything below it
        here makes the answer wrong or unanswerable."""
        request = _builder(budget=_budget_after(3)).build(_full_inputs())
        assert request.output_schema is None
        assert _PREFERRED_INSTRUCTION not in _instructions_of(request)
        assert request.knowledge_base_state == _KNOWLEDGE_BASE_STATE

    def test_the_knowledge_base_state_goes_next(self) -> None:
        request = _builder(budget=_budget_after(4)).build(_full_inputs())
        assert _PREFERRED_INSTRUCTION not in _instructions_of(request)
        assert request.knowledge_base_state is None
        assert request.rolling_summary == _ROLLING_SUMMARY

    def test_the_rolling_summary_goes_next(self) -> None:
        request = _builder(budget=_budget_after(5)).build(_full_inputs())
        assert request.knowledge_base_state is None
        assert request.rolling_summary is None
        assert request.relevant_memory == _RELEVANT_MEMORY

    def test_relevant_memory_goes_next(self) -> None:
        request = _builder(budget=_budget_after(6)).build(_full_inputs())
        assert request.rolling_summary is None
        assert request.relevant_memory == ()
        assert request.pinned_memory == _PINNED_MEMORY

    def test_pinned_memory_goes_next(self) -> None:
        """Relevant memory before pinned: a fact the student fixed in place outranks one
        the memory store merely judged relevant to this turn."""
        request = _builder(budget=_budget_after(7)).build(_full_inputs())
        assert request.relevant_memory == ()
        assert request.pinned_memory == ()
        assert request.conversation_history == _CONVERSATION_HISTORY

    def test_conversation_history_goes_next(self) -> None:
        request = _builder(budget=_budget_after(8)).build(_full_inputs())
        assert request.pinned_memory == ()
        assert request.conversation_history == ()
        assert _REQUIRED_INSTRUCTION in _instructions_of(request)

    def test_required_requirements_are_the_last_thing_given_up(self) -> None:
        """Dropping the conversation that made the question answerable is worse than
        dropping a rule about how to answer it, so the rule goes after."""
        request = _builder(budget=_budget_after(9)).build(_full_inputs())
        assert request.conversation_history == ()
        assert _REQUIRED_INSTRUCTION not in _instructions_of(request)


# ---------------------------------------------------------------------------
# What is never touched
# ---------------------------------------------------------------------------


class TestEssentialsAreNeverShed:
    def test_safety_rules_survive_an_impossible_budget(self) -> None:
        """The rule this exists to guard: security policy is never the slot that gets
        dropped, however far under budget the prompt runs."""
        request = _builder(budget=1).build(_full_inputs())
        assert request.safety_rules == _SAFETY_RULES

    def test_a_critical_requirement_survives_an_impossible_budget(self) -> None:
        """A requirement classified critical is a requirement no budget may trade away —
        the classification would mean nothing if the token count could overrule it."""
        request = _builder(budget=1).build(_full_inputs())
        assert _instructions_of(request) == [_CRITICAL_INSTRUCTION]

    def test_the_system_preamble_survives_an_impossible_budget(self) -> None:
        request = _builder(budget=1).build(_full_inputs())
        assert request.system_preamble == _SYSTEM_PREAMBLE

    def test_the_task_instructions_survive_an_impossible_budget(self) -> None:
        request = _builder(budget=1).build(_full_inputs())
        assert request.task_instructions == _TASK_INSTRUCTIONS

    def test_the_question_survives_an_impossible_budget(self) -> None:
        request = _builder(budget=1).build(_full_inputs())
        assert request.query == _QUERY

    def test_evidence_survives_an_impossible_budget(self) -> None:
        """Retrieval already spent four steps sizing and compressing this to fit its own
        budget. This module has no authority to decide which passage goes."""
        evidence = (LabeledPassage(label="[S1]", text=UntrustedText("A passage of evidence.")),)
        request = _builder(budget=1).build(_full_inputs(evidence=evidence))
        assert request.evidence == evidence

    def test_every_sheddable_slot_is_cleared_when_the_essentials_alone_do_not_fit(
        self,
    ) -> None:
        """There is nothing left this module is allowed to cut, so it returns what it can
        rather than raising — the caller sends an over-budget prompt, which is still a
        prompt, rather than none at all."""
        request = _builder(budget=1).build(_full_inputs())
        assert request.critical_checklist == ()
        assert request.output_schema is None
        assert request.knowledge_base_state is None
        assert request.rolling_summary is None
        assert request.relevant_memory == ()
        assert request.pinned_memory == ()
        assert request.conversation_history == ()


# ---------------------------------------------------------------------------
# Instructions become named requirements before any of the above runs
# ---------------------------------------------------------------------------


class TestInstructionsBecomeRequirements:
    def test_every_requirement_in_a_built_prompt_carries_a_name(self) -> None:
        request = _builder(budget=_FULL_COST).build(_full_inputs())
        assert [r.identifier for r in request.mandatory_requirements] == ["R1", "R2", "R3"]

    def test_requirements_are_named_in_reading_order_not_the_order_supplied(self) -> None:
        request = _builder(budget=_FULL_COST).build(_full_inputs())
        named = {r.identifier: r.instruction for r in request.mandatory_requirements}
        assert named["R1"] is _CRITICAL_INSTRUCTION
        assert named["R3"] is _REQUIRED_INSTRUCTION

    def test_a_contradicted_instruction_never_reaches_the_prompt(self) -> None:
        """Resolution runs before assembly, so a conflict is settled once rather than left
        for the model to notice halfway through reading the requirements."""
        superseded = Instruction(
            text="Brief.",
            category=InstructionCategory.USER_CONSTRAINT,
            level=RequirementLevel.PREFERRED,
            subject="length",
        )
        winner = Instruction(
            text="Full.",
            category=InstructionCategory.USER_CONSTRAINT,
            level=RequirementLevel.REQUIRED,
            subject="length",
        )
        request = _builder(budget=_FULL_COST * 10).build(
            _full_inputs(instructions=(superseded, winner))
        )
        assert _instructions_of(request) == [winner]

    def test_shedding_leaves_the_surviving_names_alone(self) -> None:
        """A gap where R2 used to be is the honest record — a reader who finds it missing
        knows it was not sent, where renumbering would show nothing at all."""
        middle = Instruction(
            text="Brief.",
            category=InstructionCategory.USER_CONSTRAINT,
            level=RequirementLevel.PREFERRED,
        )
        last = Instruction(
            text="Cite.",
            category=InstructionCategory.STYLE_PREFERENCE,
            level=RequirementLevel.REQUIRED,
        )
        request = _builder(budget=_budget_after(3)).build(
            _full_inputs(instructions=(_CRITICAL_INSTRUCTION, middle, last))
        )
        assert [r.identifier for r in request.mandatory_requirements] == ["R1", "R3"]


# ---------------------------------------------------------------------------
# Independent tasks get their own prompt
# ---------------------------------------------------------------------------


class TestIndependentTasks:
    def test_each_task_becomes_its_own_request(self) -> None:
        requests = _builder(budget=_FULL_COST * 10).build_all(
            (_full_inputs(query="first question"), _full_inputs(query="second question"))
        )
        assert [r.query for r in requests] == ["first question", "second question"]

    def test_neither_task_sheds_anything_to_make_room_for_the_other(self) -> None:
        """The point of separating them. Combined, the two would share one budget and one
        of them would lose context it needs to an ordering that never saw the other task."""
        requests = _builder(budget=_FULL_COST).build_all((_full_inputs(), _full_inputs()))
        assert all(r.critical_checklist == _CRITICAL_CHECKLIST for r in requests)

    def test_building_one_task_is_the_same_as_building_a_sequence_of_one(self) -> None:
        inputs = _full_inputs()
        builder = _builder(budget=_FULL_COST)
        assert builder.build(inputs) == builder.build_all((inputs,))[0]

    def test_no_tasks_at_all_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError, match="at least one task"):
            _builder(budget=_FULL_COST).build_all(())


# ---------------------------------------------------------------------------
# Absent inputs
# ---------------------------------------------------------------------------


class TestAbsentInputs:
    def test_nothing_to_shed_is_not_an_error(self) -> None:
        """Most of these slots have no producer yet, and that is the ordinary case, not
        a degenerate one."""
        minimal = ContextInputs(
            model_task=ModelTask.ANSWER_GENERATION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=_SAFETY_RULES,
            task_instructions=_TASK_INSTRUCTIONS,
            query=_QUERY,
        )
        request = _builder(budget=1).build(minimal)
        assert request.query == _QUERY
        assert request.critical_checklist == ()
        assert request.mandatory_requirements == ()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_a_budget_of_zero_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError):
            ContextBuilder(_count_words, token_budget=0)

    def test_a_negative_budget_is_rejected(self) -> None:
        with pytest.raises(InvariantViolationError):
            ContextBuilder(_count_words, token_budget=-10)
