"""Assemble the twelve-slot prompt, and decide what to drop when it will not fit.

Ordering and budgeting are two different problems that happen to live in one place. The
order is fixed by what the model needs to read first to make sense of what comes after:
who it is and what it must never do, then what this turn asks of it, then the context that
turn is answered inside, then the evidence, then the question, then how to answer it. A
provider adapter that received the slots in a different order would still work — nothing
about a chat API enforces this — but a security rule buried after the evidence reads as
one opinion among many rather than as the rule it is.

The budget problem is separate: everything above might not fit. Something has to go, and
not everything is equally safe to lose. A student's pinned preference for short answers is
worth keeping and worth losing if it comes to that; the passages the answer must be
grounded in are not worth losing under any circumstance this module controls, because
without them there is no answer to give, only a guess with a citation nobody checked. So
this shrinks the parts of the prompt that make an answer better before it ever touches the
parts that make an answer possible.

What is never touched: the system identity and safety rules, the task itself, the evidence
retrieval already spent four steps sizing and compressing to fit its own budget, the
question, and any requirement that binds critically. If those alone exceed what is left
after shedding everything else, the request is returned as it is — there is nothing here
with the authority to cut further, and pretending otherwise would mean silently deciding
which passage to drop, which the steps that sized the evidence already did and this one
must not redo.

The turn's requirements arrive as instructions and leave as a numbered list, because the
budget is not the only thing that can remove one. Two instructions can also contradict
each other, and settling that is the work of `instructions`; what happens here is that the
settling runs before any of this does, so what gets numbered is what will actually be sent
and a requirement dropped for contradicting another one is never given a name at all.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from app.domain.enums import ModelTask, RequirementLevel
from app.domain.errors import InvariantViolationError
from app.domain.invariants import require_positive
from app.domain.models.entities import ConversationTurn, LabeledPassage, ModelRequest
from app.domain.models.instructions import (
    Instruction,
    NumberedRequirement,
    resolve_instructions,
)


@dataclass(frozen=True, slots=True)
class ContextInputs:
    """Everything a turn could put in the prompt, before any budget is applied.

    Only five fields are required. Every other slot defaults to absent, which is the
    honest state of most of them today: nothing in this codebase yet produces a Knowledge
    Base summary, pinned memory, a rolling summary, an output schema or a checklist. The
    default lets the builder be used now, by the one caller that exists, rather than
    waiting for all twelve producers to.

    Instructions arrive unsettled and unnamed. Contradictions between them have not been
    resolved yet and nothing has a number, because both of those depend on the whole set
    and neither is a caller's business to work out one instruction at a time.
    """

    model_task: ModelTask
    system_preamble: str
    safety_rules: tuple[str, ...]
    task_instructions: str
    query: str
    instructions: tuple[Instruction, ...] = ()
    knowledge_base_state: str | None = None
    pinned_memory: tuple[str, ...] = ()
    relevant_memory: tuple[str, ...] = ()
    rolling_summary: str | None = None
    conversation_history: tuple[ConversationTurn, ...] = ()
    evidence: tuple[LabeledPassage, ...] = ()
    output_schema: str | None = None
    critical_checklist: tuple[str, ...] = ()
    max_tokens: int | None = None
    temperature: float | None = None


def _without(
    requirements: tuple[NumberedRequirement, ...], level: RequirementLevel
) -> tuple[NumberedRequirement, ...]:
    """Every requirement except those binding at exactly this strength.

    Removal is by whole requirement, so what survives keeps the name it was given. The gaps
    that leaves in the numbering are the honest record: a reader who finds R2 missing knows
    it was not sent, where a renumbered list would show nothing at all.
    """
    return tuple(r for r in requirements if r.instruction.level is not level)


#: Gives up one slot at a time, in the order slots are given up — first here, first
#: discarded. Everything not represented is essential and untouched by any of these: the
#: system identity and safety rules, the task, the evidence, the question, and any
#: requirement binding critically. Each step gives up a whole slot, or a whole class of
#: requirements within one, rather than trimming: half a Knowledge Base summary or half a
#: conversation history reads as complete and is not, which is worse than being visibly
#: absent. Written as typed functions rather than a name-and-value table so each `replace`
#: call is checked against the entity it targets.
#:
#: Preferences go early and rules go last, either side of everything else. A preference
#: unmet makes an answer less pleasant to read; a rule unmet makes it the wrong answer,
#: and dropping the conversation that made the question answerable is worse still — so the
#: merely required requirements are the last thing surrendered before nothing is left to
#: surrender.
_SHEDDING_STEPS: tuple[Callable[[ModelRequest], ModelRequest], ...] = (
    lambda r: replace(r, critical_checklist=()),
    lambda r: replace(r, output_schema=None),
    lambda r: replace(
        r, mandatory_requirements=_without(r.mandatory_requirements, RequirementLevel.PREFERRED)
    ),
    lambda r: replace(r, knowledge_base_state=None),
    lambda r: replace(r, rolling_summary=None),
    lambda r: replace(r, relevant_memory=()),
    lambda r: replace(r, pinned_memory=()),
    lambda r: replace(r, conversation_history=()),
    lambda r: replace(
        r, mandatory_requirements=_without(r.mandatory_requirements, RequirementLevel.REQUIRED)
    ),
)


class ContextBuilder:
    """Turn a turn's raw inputs into the ordered prompt the model actually receives."""

    def __init__(self, count_tokens: Callable[[str], int], *, token_budget: int) -> None:
        require_positive(token_budget, "token_budget")
        self._count = count_tokens
        self._budget = token_budget

    def build(self, inputs: ContextInputs) -> ModelRequest:
        """The assembled request for a single task, shed down until it fits the budget."""
        return self.build_all((inputs,))[0]

    def build_all(self, tasks: Sequence[ContextInputs]) -> tuple[ModelRequest, ...]:
        """One request per task, because independent tasks do not belong in one prompt.

        Not merely tidier. Two tasks sharing a prompt share a budget, so the context one of
        them needs is shed to make room for the other's, and which one loses is decided by
        an ordering that was never told there were two tasks. They also share a single task
        objective, which then has to describe both, and a checklist that has to be read as
        applying to whichever half is being written at the time.

        Separate calls give each task the whole budget and an objective about nothing else.
        """
        if not tasks:
            raise InvariantViolationError("build_all requires at least one task")
        return tuple(self._build_one(task) for task in tasks)

    def _build_one(self, inputs: ContextInputs) -> ModelRequest:
        request = ModelRequest(
            model_task=inputs.model_task,
            system_preamble=inputs.system_preamble,
            safety_rules=inputs.safety_rules,
            task_instructions=inputs.task_instructions,
            query=inputs.query,
            mandatory_requirements=resolve_instructions(inputs.instructions),
            knowledge_base_state=inputs.knowledge_base_state,
            pinned_memory=inputs.pinned_memory,
            relevant_memory=inputs.relevant_memory,
            rolling_summary=inputs.rolling_summary,
            conversation_history=inputs.conversation_history,
            evidence=inputs.evidence,
            output_schema=inputs.output_schema,
            critical_checklist=inputs.critical_checklist,
            max_tokens=inputs.max_tokens,
            temperature=inputs.temperature,
        )

        for shed in _SHEDDING_STEPS:
            if self._cost(request) <= self._budget:
                break
            request = shed(request)

        return request

    def _cost(self, request: ModelRequest) -> int:
        """The request's size, as the sum of what each slot would cost to send.

        Not a rendering of the final provider payload — that varies per provider and is
        the normalizer's job, not the domain's — but the same approximation the rest of
        this pipeline already trusts: the token count of the text a slot carries.
        """
        parts: list[str] = [request.system_preamble, *request.safety_rules]
        parts.append(request.task_instructions)
        parts.extend(requirement.rendered for requirement in request.mandatory_requirements)
        if request.knowledge_base_state:
            parts.append(request.knowledge_base_state)
        parts.extend(request.pinned_memory)
        parts.extend(request.relevant_memory)
        if request.rolling_summary:
            parts.append(request.rolling_summary)
        parts.extend(turn.content.value for turn in request.conversation_history)
        parts.extend(passage.text.value for passage in request.evidence)
        parts.append(request.query)
        if request.output_schema:
            parts.append(request.output_schema)
        parts.extend(request.critical_checklist)
        return sum(self._count(part) for part in parts)
