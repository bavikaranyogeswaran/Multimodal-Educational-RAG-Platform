"""LLM-backed query decomposition adapter."""

from __future__ import annotations

import json

from app.domain.enums import ModelTask
from app.domain.errors import DecompositionError
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.retrieval.decomposition import SubQuestion

_SYSTEM_PREAMBLE = (
    "You are an expert at breaking down complex questions into focused sub-questions. "
    "You identify the distinct pieces of knowledge needed to fully answer a question "
    "and express each as a clear, self-contained sub-question. "
    "You return only valid JSON matching the requested schema, with no commentary."
)

_TASK_INSTRUCTIONS = """\
Decompose the question below into sub-questions that together cover everything needed \
to answer it fully.

Return a JSON array where each item has:
- "id": a short stable key like "Q1", "Q2", etc.
- "text": a clear, self-contained sub-question
- "depends_on": a list of ids whose answers this sub-question builds on (usually empty)

Rules:
- Only create sub-questions that are genuinely distinct and necessary.
- A simple question that needs no decomposition should return a single-item array.
- "depends_on" must only reference ids that appear earlier in the array.
- Respond with a JSON array only — no markdown fences, no commentary."""

_OUTPUT_SCHEMA = (
    '[{"id": "Q1", "text": "sub-question text", "depends_on": []}]'
)


class LlmQueryDecomposition:
    """Calls the configured model gateway to decompose a query into sub-questions."""

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def decompose(
        self,
        query: str,
        *,
        max_sub_questions: int,
    ) -> list[SubQuestion]:
        request = ModelRequest(
            model_task=ModelTask.MULTI_HOP_DECOMPOSITION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS,
            query=query,
            output_schema=_OUTPUT_SCHEMA,
            max_tokens=1024,
            temperature=0.0,
        )
        response = await self._gateway.generate(request)
        return _parse(response.content.value, max_sub_questions)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        return "\n".join(inner)
    return text


def _parse(raw: str, max_sub_questions: int) -> list[SubQuestion]:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise DecompositionError(
            f"decomposition output is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise DecompositionError("decomposition output must be a JSON array")

    results: list[SubQuestion] = []
    for i, item in enumerate(data[:max_sub_questions]):
        if not isinstance(item, dict):
            raise DecompositionError(f"sub-question at index {i} must be a JSON object")

        sq_id = item.get("id", "")
        if not isinstance(sq_id, str) or not sq_id.strip():
            raise DecompositionError(f"sub-question at index {i} has a blank or missing id")

        text = item.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise DecompositionError(f"sub-question at index {i} has blank or missing text")

        raw_deps = item.get("depends_on", [])
        if not isinstance(raw_deps, list):
            raise DecompositionError(
                f"sub-question {sq_id!r}: depends_on must be a list"
            )
        depends_on = frozenset(str(d) for d in raw_deps if isinstance(d, str))

        results.append(SubQuestion(id=sq_id.strip(), text=text.strip(), depends_on=depends_on))

    if not results:
        raise DecompositionError("decomposition produced no sub-questions")

    return results
