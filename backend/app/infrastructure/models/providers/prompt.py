"""Provider-neutral prompt rendering.

Maps the twelve-slot ModelRequest to the role-based chat message array that
both Ollama and the OpenAI-compatible API accept. The PromptProfile dataclass
carries per-adapter rendering options so the same ModelRequest can be
formatted differently for providers that respond better to different layouts.

The acknowledged-exchange pattern — sending context as a user-then-assistant
pair rather than as a bare system block — is deliberate: a fact the model has
read and confirmed in the exchange is attended to differently than the same
fact folded into an instruction block the model never acknowledged.
Providers that do not benefit from this pattern can set
use_acknowledged_exchange=False in their profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import MessageRole
from app.domain.models.entities import ModelRequest


@dataclass(frozen=True, slots=True)
class PromptProfile:
    """Per-adapter rendering options for the chat message array.

    Adapters declare a PromptProfile at construction time and pass it to
    build_chat_messages. The profile controls formatting choices that vary
    across providers without changing the underlying ModelRequest structure.

    use_acknowledged_exchange: when True, memory and evidence slots are each
        wrapped in a user-then-assistant pair so the model processes context
        it has explicitly acknowledged. When False, each slot is a single user
        message with no assistant reply — suited to providers that treat
        assistant pre-fills as part of their own turn budget.
    """

    use_acknowledged_exchange: bool = True


DEFAULT_PROMPT_PROFILE = PromptProfile()


def build_chat_messages(
    request: ModelRequest,
    profile: PromptProfile = DEFAULT_PROMPT_PROFILE,
) -> list[dict[str, str]]:
    """Render a ModelRequest as an ordered list of role-based chat messages.

    The system message combines every structural slot: identity, safety rules,
    the task, this turn's requirements, and the Knowledge Base state. Each
    context slot is either wrapped in a user-then-assistant acknowledged
    exchange (profile.use_acknowledged_exchange=True) or emitted as a bare
    user message (False), depending on the profile.

    Slot order:
        system   — preamble + safety + task + requirements + KB state
        user[/a] — memory (pinned + relevant + rolling summary)
        user     — conversation history turns, verbatim
        user[/a] — evidence passages
        user     — the current question
        user     — output schema (if present)
        user     — critical checklist (if present)
    """
    system_parts = [request.system_preamble, *request.safety_rules, request.task_instructions]
    system_parts.extend(requirement.rendered for requirement in request.mandatory_requirements)
    if request.knowledge_base_state:
        system_parts.append(request.knowledge_base_state)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
    ]

    memory = [*request.pinned_memory, *request.relevant_memory]
    if request.rolling_summary:
        memory.append(request.rolling_summary)
    if memory:
        facts = "\n".join(f"- {fact}" for fact in memory)
        messages.append({"role": "user", "content": f"[Student context]\n{facts}"})
        if profile.use_acknowledged_exchange:
            messages.append({"role": "assistant", "content": "Understood, I have noted the context."})

    for turn in request.conversation_history:
        role = "user" if turn.role is MessageRole.USER else "assistant"
        messages.append({"role": role, "content": turn.content.value})

    if request.evidence:
        passages = "\n\n".join(f"{p.label} {p.text.value}" for p in request.evidence)
        messages.append({"role": "user", "content": f"[Reference material]\n{passages}"})
        if profile.use_acknowledged_exchange:
            messages.append({"role": "assistant", "content": "I have reviewed the material."})

    messages.append({"role": "user", "content": request.query})

    if request.output_schema:
        messages.append({"role": "user", "content": f"[Required output format]\n{request.output_schema}"})

    if request.critical_checklist:
        points = "\n".join(f"- {point}" for point in request.critical_checklist)
        messages.append({"role": "user", "content": f"[Before you answer]\n{points}"})

    return messages
