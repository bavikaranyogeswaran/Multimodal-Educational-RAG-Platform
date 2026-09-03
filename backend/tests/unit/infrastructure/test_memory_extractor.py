"""Tests for LlmMemoryExtractor against a mocked ModelGateway."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType, ModelTask
from app.domain.errors import MemoryExtractionError
from app.domain.models.entities import ModelResponse
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.memory.extractor import LlmMemoryExtractor

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_gateway(response_json: str) -> AsyncMock:
    response = ModelResponse(
        model_task=ModelTask.MEMORY_EXTRACTION,
        model_id="test-model",
        content=UntrustedText(response_json),
        prompt_tokens=10,
        completion_tokens=40,
        finish_reason="stop",
    )
    gateway = AsyncMock()
    gateway.generate = AsyncMock(return_value=response)
    return gateway


def _extractor(response_json: str) -> LlmMemoryExtractor:
    return LlmMemoryExtractor(model_gateway=_make_gateway(response_json))


def _valid_payload(facts: list[dict] | None = None) -> str:
    return json.dumps(facts or [
        {
            "memory_type": "GOAL",
            "key": "learning_goal",
            "value": {"goal": "pass the ML exam"},
            "confidence": 0.9,
        }
    ])


async def _run(
    extractor: LlmMemoryExtractor,
    *,
    user_message: str = "I want to pass the ML exam.",
    assistant_message: str = "I can help you prepare for that.",
) -> list:
    scope = _scope()
    return await extractor.extract(
        scope,
        user_message=user_message,
        assistant_message=assistant_message,
        source_message_id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_returns_correct_fields(self) -> None:
        facts = await _run(_extractor(_valid_payload()))

        assert len(facts) == 1
        fact = facts[0]
        assert fact.memory_type == MemoryType.GOAL
        assert fact.key == "learning_goal"
        assert fact.value == {"goal": "pass the ML exam"}
        assert fact.confidence == 0.9

    async def test_fact_carries_scope(self) -> None:
        extractor = _extractor(_valid_payload())
        scope = _scope()
        source_id = uuid.uuid4()
        facts = await extractor.extract(
            scope,
            user_message="I want to pass the ML exam.",
            assistant_message="I can help.",
            source_message_id=source_id,
        )

        assert facts[0].user_id == scope.user_id
        assert facts[0].knowledge_base_id == scope.knowledge_base_id
        assert facts[0].source_message_id == source_id

    async def test_provenance_is_always_assistant_inference(self) -> None:
        facts = await _run(_extractor(_valid_payload()))
        assert facts[0].provenance == MemoryProvenance.ASSISTANT_INFERENCE

    async def test_status_is_always_active(self) -> None:
        facts = await _run(_extractor(_valid_payload()))
        assert facts[0].status == MemoryStatus.ACTIVE

    async def test_empty_array_is_valid(self) -> None:
        facts = await _run(_extractor("[]"))
        assert facts == []

    async def test_multiple_facts_returned(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "goal", "value": {"text": "pass exam"}, "confidence": 0.9},
            {"memory_type": "WEAK_TOPIC", "key": "weak_calculus", "value": {"topic": "integration"}, "confidence": 0.7},
        ])
        facts = await _run(_extractor(payload))
        assert len(facts) == 2

    async def test_confidence_clamped_below_zero(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "goal", "value": {"text": "x"}, "confidence": -0.5},
        ])
        facts = await _run(_extractor(payload))
        assert facts[0].confidence == 0.0

    async def test_confidence_clamped_above_one(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "goal", "value": {"text": "x"}, "confidence": 1.5},
        ])
        facts = await _run(_extractor(payload))
        assert facts[0].confidence == 1.0

    async def test_bad_confidence_defaults_to_half(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "goal", "value": {"text": "x"}, "confidence": "bad"},
        ])
        facts = await _run(_extractor(payload))
        assert facts[0].confidence == 0.5

    async def test_duplicate_key_keeps_first(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "same_key", "value": {"v": 1}, "confidence": 0.8},
            {"memory_type": "GOAL", "key": "same_key", "value": {"v": 2}, "confidence": 0.6},
        ])
        facts = await _run(_extractor(payload))
        assert len(facts) == 1
        assert facts[0].value == {"v": 1}

    async def test_unknown_memory_type_is_silently_skipped(self) -> None:
        payload = _valid_payload([
            {"memory_type": "INVENTED_TYPE", "key": "k", "value": {"x": 1}, "confidence": 0.8},
            {"memory_type": "GOAL", "key": "goal", "value": {"text": "x"}, "confidence": 0.9},
        ])
        facts = await _run(_extractor(payload))
        assert len(facts) == 1
        assert facts[0].key == "goal"

    async def test_strips_markdown_code_fences(self) -> None:
        fenced = "```json\n" + _valid_payload() + "\n```"
        facts = await _run(_extractor(fenced))
        assert len(facts) == 1

    async def test_strips_fences_without_language_tag(self) -> None:
        fenced = "```\n" + _valid_payload() + "\n```"
        facts = await _run(_extractor(fenced))
        assert len(facts) == 1

    async def test_all_valid_memory_types_accepted(self) -> None:
        for mt in MemoryType:
            payload = _valid_payload([
                {"memory_type": mt.value, "key": "k", "value": {"x": 1}, "confidence": 0.8},
            ])
            facts = await _run(_extractor(payload))
            assert facts[0].memory_type == mt

    async def test_calls_model_gateway_with_memory_extraction_task(self) -> None:
        gateway = _make_gateway(_valid_payload())
        extractor = LlmMemoryExtractor(model_gateway=gateway)
        scope = _scope()

        await extractor.extract(
            scope,
            user_message="u",
            assistant_message="a",
            source_message_id=uuid.uuid4(),
        )

        request = gateway.generate.call_args[0][0]
        assert request.model_task == ModelTask.MEMORY_EXTRACTION
        assert request.temperature == 0.0


# ---------------------------------------------------------------------------
# validation failures
# ---------------------------------------------------------------------------


class TestValidationFailures:
    async def test_malformed_json_raises(self) -> None:
        with pytest.raises(MemoryExtractionError, match="not valid JSON"):
            await _run(_extractor("not json at all"))

    async def test_non_array_root_raises(self) -> None:
        with pytest.raises(MemoryExtractionError, match="JSON array"):
            await _run(_extractor(json.dumps({"key": "value"})))

    async def test_fact_not_object_raises(self) -> None:
        with pytest.raises(MemoryExtractionError, match="fact at index 0"):
            await _run(_extractor(json.dumps(["not a dict"])))

    async def test_blank_key_raises(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "", "value": {"x": 1}, "confidence": 0.8},
        ])
        with pytest.raises(MemoryExtractionError, match="blank or missing key"):
            await _run(_extractor(payload))

    async def test_whitespace_only_key_raises(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "   ", "value": {"x": 1}, "confidence": 0.8},
        ])
        with pytest.raises(MemoryExtractionError, match="blank or missing key"):
            await _run(_extractor(payload))

    async def test_value_not_dict_raises(self) -> None:
        payload = _valid_payload([
            {"memory_type": "GOAL", "key": "goal", "value": "not a dict", "confidence": 0.8},
        ])
        with pytest.raises(MemoryExtractionError, match="value must be a JSON object"):
            await _run(_extractor(payload))
