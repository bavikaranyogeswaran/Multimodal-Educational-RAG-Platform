"""LLM-backed graph entity and relationship extractor."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from app.domain.enums import GraphNodeType, ModelTask, RelationshipType
from app.domain.errors import GraphExtractionError
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_SYSTEM_PREAMBLE = (
    "You extract structured knowledge from educational text. "
    "You identify concepts, definitions, figures, and tables as entities, "
    "and the precise relationships between them. "
    "You return only valid JSON matching the requested schema, with no commentary."
)

_TASK_INSTRUCTIONS = """\
Extract all notable entities and relationships from the passage below.

Return a JSON object with exactly two arrays:
- "entities": each item has "name" (non-empty string), "type" (one of: \
Concept, Chapter, Section, Figure, Table), and optional "description" (string).
- "relationships": each item has "source" (entity name), "target" (entity name), \
"type" (one of: CONTAINS, PART_OF, DEFINED_IN, RELATED_TO, PREREQUISITE_OF, \
COMPARES_WITH, EXPLAINED_BY, SHOWN_IN, REFERENCES), and "evidence" (a short quote \
or paraphrase from the passage that supports the relationship; must not be empty).

Rules:
- Only include entities and relationships explicitly supported by the passage.
- "source" and "target" must both appear in the "entities" array.
- "evidence" must not be empty.
- Do not include KnowledgeBase or Document type nodes.
- Respond with JSON only — no markdown fences, no commentary."""

_OUTPUT_SCHEMA = (
    '{"entities": [{"name": "string", "type": "Concept|Chapter|Section|Figure|Table", '
    '"description": "optional string"}], '
    '"relationships": [{"source": "entity name", "target": "entity name", '
    '"type": "CONTAINS|PART_OF|DEFINED_IN|RELATED_TO|PREREQUISITE_OF|COMPARES_WITH|'
    'EXPLAINED_BY|SHOWN_IN|REFERENCES", "evidence": "non-empty string"}]}'
)

# Structural node types that the model must not produce.
_FORBIDDEN_TYPES = {"KnowledgeBase", "Document"}
_VALID_ENTITY_TYPES = {t.value for t in GraphNodeType} - _FORBIDDEN_TYPES
_VALID_REL_TYPES = {t.value for t in RelationshipType}


class LlmGraphExtractor:
    """Calls the configured model gateway to extract graph entities and relationships.

    The output is provisional — entities are not yet deduplicated or assigned
    canonical names. The BUILD_GRAPH worker passes them through GraphDeduplicator
    before writing to the repository.
    """

    def __init__(self, model_gateway: ModelGatewayPort) -> None:
        self._gateway = model_gateway

    async def extract(
        self,
        scope: ScopeContext,
        *,
        text: str,
        document_id: UUID,
        chunk_id: UUID,
        page_number: int,
    ) -> tuple[list[GraphEntity], list[GraphRelationship]]:
        request = ModelRequest(
            model_task=ModelTask.GRAPH_EXTRACTION,
            system_preamble=_SYSTEM_PREAMBLE,
            safety_rules=(),
            task_instructions=_TASK_INSTRUCTIONS,
            query=text,
            output_schema=_OUTPUT_SCHEMA,
            max_tokens=2048,
            temperature=0.0,
        )
        response = await self._gateway.generate(request)
        return _parse_and_validate(
            response.content.value, scope, document_id, chunk_id, page_number
        )


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences that some models wrap JSON in."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop the opening fence line and, if present, the closing fence.
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        return "\n".join(inner)
    return text


def _parse_and_validate(
    raw: str,
    scope: ScopeContext,
    document_id: UUID,
    chunk_id: UUID,
    page_number: int,
) -> tuple[list[GraphEntity], list[GraphRelationship]]:
    try:
        data = json.loads(_strip_fences(raw))
    except json.JSONDecodeError as exc:
        raise GraphExtractionError(
            f"graph extraction output is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise GraphExtractionError("graph extraction output must be a JSON object")

    raw_entities = data.get("entities", [])
    raw_rels = data.get("relationships", [])

    if not isinstance(raw_entities, list):
        raise GraphExtractionError("'entities' must be a JSON array")
    if not isinstance(raw_rels, list):
        raise GraphExtractionError("'relationships' must be a JSON array")

    now = datetime.now(UTC)
    entities: list[GraphEntity] = []
    name_to_entity: dict[str, GraphEntity] = {}

    for i, raw_ent in enumerate(raw_entities):
        if not isinstance(raw_ent, dict):
            raise GraphExtractionError(f"entity at index {i} must be a JSON object")

        name = raw_ent.get("name", "")
        if not isinstance(name, str) or not name.strip():
            raise GraphExtractionError(f"entity at index {i} has a blank or missing name")

        type_str = raw_ent.get("type", "")
        if type_str not in _VALID_ENTITY_TYPES:
            raise GraphExtractionError(
                f"entity at index {i} has unrecognised type {type_str!r}"
            )

        raw_desc = raw_ent.get("description")
        description: str | None = None
        if isinstance(raw_desc, str) and raw_desc.strip():
            description = raw_desc.strip()

        entity = GraphEntity(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            entity_type=GraphNodeType(type_str),
            name=name.strip(),
            description=description,
            source_document_id=document_id,
            source_chunk_id=chunk_id,
            page_number=page_number,
            created_at=now,
            updated_at=now,
        )
        entities.append(entity)
        name_to_entity[entity.name] = entity

    relationships: list[GraphRelationship] = []

    for i, raw_rel in enumerate(raw_rels):
        if not isinstance(raw_rel, dict):
            raise GraphExtractionError(f"relationship at index {i} must be a JSON object")

        source_name = raw_rel.get("source", "")
        target_name = raw_rel.get("target", "")
        rel_type_str = raw_rel.get("type", "")
        evidence_str = raw_rel.get("evidence", "")

        if not isinstance(source_name, str) or not source_name.strip():
            raise GraphExtractionError(f"relationship at index {i} has a blank source")
        if not isinstance(target_name, str) or not target_name.strip():
            raise GraphExtractionError(f"relationship at index {i} has a blank target")

        source_name = source_name.strip()
        target_name = target_name.strip()

        if source_name not in name_to_entity:
            raise GraphExtractionError(
                f"relationship at index {i} source {source_name!r} is not in the extracted entities"
            )
        if target_name not in name_to_entity:
            raise GraphExtractionError(
                f"relationship at index {i} target {target_name!r} is not in the extracted entities"
            )
        if source_name == target_name:
            raise GraphExtractionError(
                f"relationship at index {i} source and target refer to the same entity {source_name!r}"
            )
        if rel_type_str not in _VALID_REL_TYPES:
            raise GraphExtractionError(
                f"relationship at index {i} has unrecognised type {rel_type_str!r}"
            )
        if not isinstance(evidence_str, str) or not evidence_str.strip():
            raise GraphExtractionError(
                f"relationship at index {i} has blank evidence (provenance invariant violated)"
            )

        relationships.append(
            GraphRelationship(
                id=uuid.uuid4(),
                user_id=scope.user_id,
                knowledge_base_id=scope.knowledge_base_id,
                source_entity_id=name_to_entity[source_name].id,
                target_entity_id=name_to_entity[target_name].id,
                relationship_type=RelationshipType(rel_type_str),
                source_chunk_id=chunk_id,
                page_number=page_number,
                evidence=UntrustedText(evidence_str.strip()),
                extraction_confidence=1.0,
                created_at=now,
                updated_at=now,
            )
        )

    return entities, relationships
