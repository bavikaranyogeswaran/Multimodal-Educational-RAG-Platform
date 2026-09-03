"""LLM-backed conversation summarizer."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.enums import ModelTask
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.scope import ScopeContext

_SYSTEM_PREAMBLE = (
    "You are a precise summarizer for an educational tutoring system. "
    "Your summaries preserve key facts, the student's goals, and any topics already "
    "covered — information a tutor would need to give coherent follow-up answers. "
    "Write in plain prose, third person, present tense. Be concise."
)

_TASK_TEMPLATE = """\
Summarize the tutoring conversation below into a short paragraph (100–200 words).
Focus on: what subject the student is studying, what they have asked about, any \
weaknesses or goals they have expressed, and what the tutor has explained so far.
{prior_section}
Conversation (oldest message first):
{turns}

Return only the summary paragraph — no headings, no bullet points."""

_PRIOR_SECTION = "Previous summary (incorporate, do not repeat verbatim):\n{summary}\n"


class LlmSummarizer:
    """Calls the model gateway to compress a conversation into a rolling summary."""

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def summarize(
        self,
        scope: ScopeContext,
        *,
        turns: Sequence[str],
        previous_summary: str | None,
    ) -> str:
        prior_section = (
            _PRIOR_SECTION.format(summary=previous_summary) if previous_summary else ""
        )
        turns_text = "\n---\n".join(turns)
        task_instructions = _TASK_TEMPLATE.format(
            prior_section=prior_section,
            turns=turns_text,
        )
        request = ModelRequest(
            model_task=ModelTask.SUMMARIZATION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=task_instructions,
            query=turns_text,
            output_schema=None,
            max_tokens=400,
            temperature=0.3,
        )
        response = await self._gateway.generate(request)
        return response.content.value.strip()
