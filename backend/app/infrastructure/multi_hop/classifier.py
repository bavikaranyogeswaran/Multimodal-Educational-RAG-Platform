"""LLM-backed query classification adapter."""

from __future__ import annotations

import structlog

from app.domain.enums import ModelTask, QueryClass
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort

_log = structlog.get_logger(__name__)

_SYSTEM_PREAMBLE = (
    "You are an expert at understanding the intent behind educational questions. "
    "You categorise each question into exactly one of thirteen types based on what "
    "kind of answer it requires. You respond with only the category name, nothing else."
)

_TASK_INSTRUCTIONS = """\
Classify the student question below into exactly one of these thirteen categories:

DIRECT          — A straightforward factual question answered from one passage.
EXACT_TERM      — Looking for a specific term, definition, equation number, or verbatim wording.
TABLE           — A question about tabular data or requesting information from a named table.
VISUAL          — A question about a figure, diagram, chart, plot, or image.
RELATIONSHIP    — Asking how two or more concepts are connected, related, or interact.
PREREQUISITE    — Asking what knowledge is needed before understanding a topic.
CONCEPT_MAP     — Requesting a comprehensive overview of how all concepts in a topic fit together.
COMPARISON      — Comparing or contrasting two or more things (similarities, differences).
MULTI_DOCUMENT  — A question that explicitly spans information across multiple documents or sources.
MULTI_HOP       — A question requiring chained reasoning where one fact depends on another.
AGGREGATION     — Asking to count, list all instances, or sum across multiple examples.
SUMMARY         — Requesting a summary, overview, key points, or recap of material.
QUIZ_GENERATION — Requesting quiz questions, test questions, or practice problems.

Rules:
- Return only the category name from the list above, in ALL_CAPS with underscores.
- When unsure, prefer DIRECT.
- Do not explain your choice."""

_OUTPUT_SCHEMA = (
    "One of: DIRECT, EXACT_TERM, TABLE, VISUAL, RELATIONSHIP, PREREQUISITE, "
    "CONCEPT_MAP, COMPARISON, MULTI_DOCUMENT, MULTI_HOP, AGGREGATION, SUMMARY, QUIZ_GENERATION"
)

_VALID_CLASSES: frozenset[str] = frozenset(qc.value for qc in QueryClass)


class LlmQueryClassifier:
    """Calls the configured model gateway to classify a query into a QueryClass.

    Unrecognised or malformed model output falls back to QueryClass.DIRECT so a
    bad classification never surfaces as an error to the student.
    """

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def classify(self, query: str) -> QueryClass:
        request = ModelRequest(
            model_task=ModelTask.QUERY_CLASSIFICATION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS,
            query=query,
            output_schema=_OUTPUT_SCHEMA,
            max_tokens=16,
            temperature=0.0,
        )
        try:
            response = await self._gateway.generate(request)
        except Exception:
            _log.warning("query_classification.gateway_error", query=query, exc_info=True)
            return QueryClass.DIRECT

        return _parse(response.content.value, query)


def _parse(raw: str, query: str) -> QueryClass:
    """Extract a QueryClass from the model's response, defaulting to DIRECT."""
    candidate = raw.strip().upper().replace("-", "_")
    if candidate in _VALID_CLASSES:
        return QueryClass(candidate)
    # Accept a partial match — the model sometimes adds trailing punctuation or prose.
    for token in candidate.split():
        clean = token.strip(".,;:!?\"'()")
        if clean in _VALID_CLASSES:
            return QueryClass(clean)
    _log.warning(
        "query_classification.unrecognised_response",
        raw=raw,
        query=query,
    )
    return QueryClass.DIRECT
