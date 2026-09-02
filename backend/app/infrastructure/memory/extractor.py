"""LLM-backed memory extraction adapter."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType, ModelTask
from app.domain.errors import MemoryExtractionError
from app.domain.memory.entities import MemoryFact
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.scope import ScopeContext

_VALID_MEMORY_TYPES = {mt.value for mt in MemoryType}

_SYSTEM_PREAMBLE = (
    "You extract durable facts about a student from a tutoring conversation. "
    "You identify stable, reusable information — goals, exam dates, topic weaknesses, "
    "constraints, or stated preferences — that would help the tutor personalise future responses. "
    "You respond with a JSON array only, no commentary."
)

_TASK_INSTRUCTIONS = """\
Read the conversation turn below and extract any durable facts about the student.

User message:
{user_message}

Assistant response:
{assistant_message}

Return a JSON array. Each item must have:
- "memory_type": one of PREFERENCE, PROJECT_DECISION, CONSTRAINT, IDENTIFIER, GOAL, EXAM_DATE, WEAK_TOPIC
- "key": a short snake_case identifier that is stable across corrections (e.g. "target_exam", "weak_topic_calculus")
- "value": a JSON object containing the fact payload (e.g. {{"date": "2026-12-01"}} or {{"topic": "integration by parts"}})
- "confidence": a float in [0.0, 1.0] reflecting how certain you are from this single turn

Rules:
- Only include facts that are clearly stated or strongly implied, not guesses.
- Return an empty array [] if there is nothing worth remembering.
- A simple question-and-answer exchange with no personal information should return [].
- "key" must be unique within the array.
- Respond with a JSON array only — no markdown fences, no commentary."""

_OUTPUT_SCHEMA = (
    '[{"memory_type": "GOAL", "key": "learning_goal", '
    '"value": {"goal": "pass ML exam"}, "confidence": 0.85}]'
)


class LlmMemoryExtractor:
    """Calls the configured model gateway to extract student facts from a conversation turn."""

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def extract(
        self,
        scope: ScopeContext,
        *,
        user_message: str,
        assistant_message: str,
        source_message_id: uuid.UUID,
    ) -> list[MemoryFact]:
        request = ModelRequest(
            model_task=ModelTask.MEMORY_EXTRACTION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS.format(
                user_message=user_message,
                assistant_message=assistant_message,
            ),
            query=user_message,
            output_schema=_OUTPUT_SCHEMA,
            max_tokens=512,
            temperature=0.0,
        )
        response = await self._gateway.generate(request)
        return _parse(response.content.value, scope, source_message_id)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        return "\n".join(inner)
    return text


def _parse(
    raw: str,
    scope: ScopeContext,
    source_message_id: uuid.UUID,
) -> list[MemoryFact]:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise MemoryExtractionError(
            f"memory extraction output is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise MemoryExtractionError("memory extraction output must be a JSON array")

    now = datetime.now(UTC)
    results: list[MemoryFact] = []
    seen_keys: set[str] = set()

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise MemoryExtractionError(f"fact at index {i} must be a JSON object")

        type_str = item.get("memory_type", "")
        if type_str not in _VALID_MEMORY_TYPES:
            continue

        key = item.get("key", "")
        if not isinstance(key, str) or not key.strip():
            raise MemoryExtractionError(f"fact at index {i} has a blank or missing key")
        key = key.strip()
        if key in seen_keys:
            continue
        seen_keys.add(key)

        value = item.get("value")
        if not isinstance(value, dict):
            raise MemoryExtractionError(
                f"fact {key!r}: value must be a JSON object"
            )

        raw_conf = item.get("confidence", 0.5)
        try:
            confidence = float(raw_conf)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        results.append(
            MemoryFact(
                id=uuid.uuid4(),
                user_id=scope.user_id,
                knowledge_base_id=scope.knowledge_base_id,
                memory_type=MemoryType(type_str),
                key=key,
                value=value,
                confidence=confidence,
                provenance=MemoryProvenance.ASSISTANT_INFERENCE,
                status=MemoryStatus.UNCONFIRMED,
                created_at=now,
                updated_at=now,
                valid_from=now,
                source_message_id=source_message_id,
            )
        )

    return results
