"""Tests for LlmGraphExtractor against a mocked ModelGateway."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import GraphNodeType, ModelTask, RelationshipType
from app.domain.errors import GraphExtractionError
from app.domain.models.entities import ModelResponse
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.graph.extractor import LlmGraphExtractor


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_gateway(response_json: str) -> AsyncMock:
    response = ModelResponse(
        model_task=ModelTask.GRAPH_EXTRACTION,
        model_id="test-model",
        content=UntrustedText(response_json),
        prompt_tokens=10,
        completion_tokens=80,
        finish_reason="stop",
    )
    gateway = AsyncMock()
    gateway.generate = AsyncMock(return_value=response)
    return gateway


def _extractor(response_json: str) -> LlmGraphExtractor:
    return LlmGraphExtractor(model_gateway=_make_gateway(response_json))


def _valid_payload(
    *,
    entities: list[dict] | None = None,
    relationships: list[dict] | None = None,
) -> str:
    return json.dumps({
        "entities": entities or [
            {"name": "Newton's Laws", "type": "Concept", "description": "Laws of motion"},
            {"name": "Momentum", "type": "Concept"},
        ],
        "relationships": relationships or [
            {
                "source": "Newton's Laws",
                "target": "Momentum",
                "type": "RELATED_TO",
                "evidence": "Newton's Laws govern the change in momentum of a body.",
            }
        ],
    })


async def _run(
    extractor: LlmGraphExtractor,
    *,
    text: str = "Some educational passage.",
    page_number: int = 3,
) -> tuple:
    scope = _scope()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    entities, rels = await extractor.extract(
        scope,
        text=text,
        document_id=doc_id,
        chunk_id=chunk_id,
        page_number=page_number,
    )
    return entities, rels, scope, doc_id, chunk_id


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_returns_entities_with_correct_fields(self) -> None:
        entities, _, scope, doc_id, chunk_id = await _run(
            _extractor(_valid_payload())
        )

        assert len(entities) == 2
        laws = next(e for e in entities if e.name == "Newton's Laws")
        assert laws.entity_type == GraphNodeType.CONCEPT
        assert laws.description == "Laws of motion"
        assert laws.user_id == scope.user_id
        assert laws.knowledge_base_id == scope.knowledge_base_id
        assert laws.source_document_id == doc_id
        assert laws.source_chunk_id == chunk_id
        assert laws.page_number == 3

    async def test_returns_relationship_with_correct_provenance(self) -> None:
        _, rels, scope, _, chunk_id = await _run(_extractor(_valid_payload()))

        assert len(rels) == 1
        rel = rels[0]
        assert rel.relationship_type == RelationshipType.RELATED_TO
        assert rel.source_chunk_id == chunk_id
        assert rel.page_number == 3
        assert "momentum" in rel.evidence.value.lower()
        assert rel.user_id == scope.user_id

    async def test_relationship_endpoints_reference_extracted_entities(self) -> None:
        entities, rels, _, _, _ = await _run(_extractor(_valid_payload()))

        entity_ids = {e.id for e in entities}
        assert rels[0].source_entity_id in entity_ids
        assert rels[0].target_entity_id in entity_ids

    async def test_empty_arrays_are_valid(self) -> None:
        payload = json.dumps({"entities": [], "relationships": []})
        entities, rels, _, _, _ = await _run(_extractor(payload))

        assert entities == []
        assert rels == []

    async def test_strips_markdown_code_fences(self) -> None:
        fenced = "```json\n" + _valid_payload() + "\n```"
        entities, rels, _, _, _ = await _run(_extractor(fenced))

        assert len(entities) == 2
        assert len(rels) == 1

    async def test_strips_fences_without_language_tag(self) -> None:
        fenced = "```\n" + _valid_payload() + "\n```"
        entities, rels, _, _, _ = await _run(_extractor(fenced))

        assert len(entities) == 2

    async def test_optional_description_absent(self) -> None:
        entities, _, _, _, _ = await _run(_extractor(_valid_payload()))

        momentum = next(e for e in entities if e.name == "Momentum")
        assert momentum.description is None

    async def test_extraction_confidence_is_set(self) -> None:
        _, rels, _, _, _ = await _run(_extractor(_valid_payload()))

        assert rels[0].extraction_confidence == 1.0

    async def test_calls_model_gateway_with_graph_extraction_task(self) -> None:
        gateway = _make_gateway(_valid_payload())
        extractor = LlmGraphExtractor(model_gateway=gateway)
        scope = _scope()

        await extractor.extract(
            scope,
            text="text",
            document_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            page_number=1,
        )

        request = gateway.generate.call_args[0][0]
        assert request.model_task == ModelTask.GRAPH_EXTRACTION
        assert request.temperature == 0.0

    async def test_all_valid_entity_types_accepted(self) -> None:
        for type_str in ("Concept", "Chapter", "Section", "Figure", "Table"):
            payload = json.dumps({
                "entities": [{"name": "X", "type": type_str}],
                "relationships": [],
            })
            entities, _, _, _, _ = await _run(_extractor(payload))
            assert entities[0].entity_type == GraphNodeType(type_str)

    async def test_all_valid_relationship_types_accepted(self) -> None:
        for rel_type in RelationshipType:
            payload = _valid_payload(
                relationships=[{
                    "source": "Newton's Laws",
                    "target": "Momentum",
                    "type": rel_type.value,
                    "evidence": "some evidence",
                }]
            )
            _, rels, _, _, _ = await _run(_extractor(payload))
            assert rels[0].relationship_type == rel_type


# ---------------------------------------------------------------------------
# validation failures
# ---------------------------------------------------------------------------


class TestValidationFailures:
    async def test_malformed_json_raises(self) -> None:
        with pytest.raises(GraphExtractionError, match="not valid JSON"):
            await _run(_extractor("not json at all"))

    async def test_non_object_root_raises(self) -> None:
        with pytest.raises(GraphExtractionError, match="JSON object"):
            await _run(_extractor(json.dumps([1, 2, 3])))

    async def test_entities_not_array_raises(self) -> None:
        with pytest.raises(GraphExtractionError, match="'entities'"):
            await _run(_extractor(json.dumps({"entities": "bad", "relationships": []})))

    async def test_relationships_not_array_raises(self) -> None:
        with pytest.raises(GraphExtractionError, match="'relationships'"):
            await _run(_extractor(json.dumps({"entities": [], "relationships": "bad"})))

    async def test_entity_not_object_raises(self) -> None:
        with pytest.raises(GraphExtractionError, match="entity at index 0"):
            await _run(_extractor(json.dumps({"entities": ["not a dict"], "relationships": []})))

    async def test_blank_entity_name_raises(self) -> None:
        payload = json.dumps({"entities": [{"name": "", "type": "Concept"}], "relationships": []})
        with pytest.raises(GraphExtractionError, match="blank or missing name"):
            await _run(_extractor(payload))

    async def test_unknown_entity_type_raises(self) -> None:
        payload = json.dumps({"entities": [{"name": "X", "type": "NotAType"}], "relationships": []})
        with pytest.raises(GraphExtractionError, match="unrecognised type"):
            await _run(_extractor(payload))

    async def test_forbidden_entity_type_knowledge_base_raises(self) -> None:
        payload = json.dumps({"entities": [{"name": "X", "type": "KnowledgeBase"}], "relationships": []})
        with pytest.raises(GraphExtractionError, match="unrecognised type"):
            await _run(_extractor(payload))

    async def test_forbidden_entity_type_document_raises(self) -> None:
        payload = json.dumps({"entities": [{"name": "X", "type": "Document"}], "relationships": []})
        with pytest.raises(GraphExtractionError, match="unrecognised type"):
            await _run(_extractor(payload))

    async def test_relationship_not_object_raises(self) -> None:
        payload = _valid_payload(relationships=["not a dict"])
        with pytest.raises(GraphExtractionError, match="relationship at index 0"):
            await _run(_extractor(payload))

    async def test_blank_relationship_source_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{"source": "", "target": "Momentum", "type": "RELATED_TO", "evidence": "e"}]
        )
        with pytest.raises(GraphExtractionError, match="blank source"):
            await _run(_extractor(payload))

    async def test_blank_relationship_target_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{"source": "Newton's Laws", "target": "", "type": "RELATED_TO", "evidence": "e"}]
        )
        with pytest.raises(GraphExtractionError, match="blank target"):
            await _run(_extractor(payload))

    async def test_source_not_in_entities_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{
                "source": "Unknown Entity",
                "target": "Momentum",
                "type": "RELATED_TO",
                "evidence": "e",
            }]
        )
        with pytest.raises(GraphExtractionError, match="not in the extracted entities"):
            await _run(_extractor(payload))

    async def test_target_not_in_entities_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{
                "source": "Newton's Laws",
                "target": "Unknown Entity",
                "type": "RELATED_TO",
                "evidence": "e",
            }]
        )
        with pytest.raises(GraphExtractionError, match="not in the extracted entities"):
            await _run(_extractor(payload))

    async def test_self_referencing_relationship_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{
                "source": "Newton's Laws",
                "target": "Newton's Laws",
                "type": "RELATED_TO",
                "evidence": "e",
            }]
        )
        with pytest.raises(GraphExtractionError, match="same entity"):
            await _run(_extractor(payload))

    async def test_unknown_relationship_type_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{
                "source": "Newton's Laws",
                "target": "Momentum",
                "type": "INVENTED_TYPE",
                "evidence": "e",
            }]
        )
        with pytest.raises(GraphExtractionError, match="unrecognised type"):
            await _run(_extractor(payload))

    async def test_blank_evidence_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{
                "source": "Newton's Laws",
                "target": "Momentum",
                "type": "RELATED_TO",
                "evidence": "",
            }]
        )
        with pytest.raises(GraphExtractionError, match="blank evidence"):
            await _run(_extractor(payload))

    async def test_whitespace_only_evidence_raises(self) -> None:
        payload = _valid_payload(
            relationships=[{
                "source": "Newton's Laws",
                "target": "Momentum",
                "type": "RELATED_TO",
                "evidence": "   ",
            }]
        )
        with pytest.raises(GraphExtractionError, match="blank evidence"):
            await _run(_extractor(payload))
