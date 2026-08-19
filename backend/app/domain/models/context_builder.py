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
retrieval already spent four steps sizing and compressing to fit its own budget, and the
question. If those alone exceed what is left after shedding everything else, the request is
returned as it is — there is nothing here with the authority to cut further, and pretending
otherwise would mean silently deciding which passage to drop, which is 10.1 through 10.4's
job and not this one's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.domain.enums import ModelTask
from app.domain.invariants import require_positive
from app.domain.models.entities import ConversationTurn, LabeledPassage, ModelRequest


@dataclass(frozen=True, slots=True)
class ContextInputs:
    """Everything a turn could put in the prompt, before any budget is applied.

    Only four fields are required. Every other slot defaults to absent, which is the
    honest state of most of them today: nothing in this codebase yet produces a Knowledge
    Base summary, pinned memory, a rolling summary, an output schema or a checklist. The
    default lets the builder be used now, by the one caller that exists, rather than
    waiting for all twelve producers to.
    """

    model_task: ModelTask
    system_preamble: str
    safety_rules: tuple[str, ...]
    task_instructions: str
    query: str
    mandatory_requirements: tuple[str, ...] = ()
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


#: Clears one slot to its empty value, in the order slots are given up — first here, first
#: discarded. Everything not represented is essential and untouched by any of these: the
#: system identity and safety rules, the task, the evidence, and the question. Each step
#: clears rather than trims its slot, because a half-sent Knowledge Base summary or half a
#: conversation history reads as complete and is not, which is worse than being visibly
#: absent. Written as typed functions rather than a name-and-value table so each `replace`
#: call is checked against the entity it targets.
_SHEDDING_STEPS: tuple[Callable[[ModelRequest], ModelRequest], ...] = (
    lambda r: replace(r, critical_checklist=()),
    lambda r: replace(r, output_schema=None),
    lambda r: replace(r, mandatory_requirements=()),
    lambda r: replace(r, knowledge_base_state=None),
    lambda r: replace(r, rolling_summary=None),
    lambda r: replace(r, relevant_memory=()),
    lambda r: replace(r, pinned_memory=()),
    lambda r: replace(r, conversation_history=()),
)


class ContextBuilder:
    """Turn a turn's raw inputs into the ordered prompt the model actually receives."""

    def __init__(self, count_tokens: Callable[[str], int], *, token_budget: int) -> None:
        require_positive(token_budget, "token_budget")
        self._count = count_tokens
        self._budget = token_budget

    def build(self, inputs: ContextInputs) -> ModelRequest:
        """The assembled request, shedding low-priority slots until it fits the budget."""
        request = ModelRequest(
            model_task=inputs.model_task,
            system_preamble=inputs.system_preamble,
            safety_rules=inputs.safety_rules,
            task_instructions=inputs.task_instructions,
            query=inputs.query,
            mandatory_requirements=inputs.mandatory_requirements,
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
        parts.extend(request.mandatory_requirements)
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
