"""Provider-neutral prompt rendering.

Maps the twelve-slot ModelRequest to the role-based chat message array that
both Ollama and the OpenAI-compatible API accept. The structure is identical
for both; step 8.7 will add per-model variations on top of this base.

The acknowledged-exchange pattern — sending context as a user-then-assistant
pair rather than as a bare system block — is deliberate: a fact the model has
read and confirmed in the exchange is attended to differently than the same
fact folded into an instruction block the model never acknowledged.
"""

from __future__ import annotations

from app.domain.enums import MessageRole
from app.domain.models.entities import ModelRequest


def build_chat_messages(request: ModelRequest) -> list[dict[str, str]]:
    """Render a ModelRequest as an ordered list of role-based chat messages.

    The system message combines every structural slot: identity, safety rules,
    the task, this turn's requirements, and the Knowledge Base state. Each
    subsequent slot arrives as a user-then-assistant acknowledged exchange so
    the model treats it as already-read context rather than as a new question.

    Slot order:
        system   — preamble + safety + task + requirements + KB state
        user/a   — memory (pinned + relevant + rolling summary), acknowledged
        user/a   — conversation history turns, verbatim
        user/a   — evidence passages, acknowledged
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
        messages.append({"role": "assistant", "content": "Understood, I have noted the context."})

    for turn in request.conversation_history:
        role = "user" if turn.role is MessageRole.USER else "assistant"
        messages.append({"role": role, "content": turn.content.value})

    if request.evidence:
        passages = "\n\n".join(f"{p.label} {p.text.value}" for p in request.evidence)
        messages.append({"role": "user", "content": f"[Reference material]\n{passages}"})
        messages.append({"role": "assistant", "content": "I have reviewed the material."})

    messages.append({"role": "user", "content": request.query})

    if request.output_schema:
        messages.append({"role": "user", "content": f"[Required output format]\n{request.output_schema}"})

    if request.critical_checklist:
        points = "\n".join(f"- {point}" for point in request.critical_checklist)
        messages.append({"role": "user", "content": f"[Before you answer]\n{points}"})

    return messages
