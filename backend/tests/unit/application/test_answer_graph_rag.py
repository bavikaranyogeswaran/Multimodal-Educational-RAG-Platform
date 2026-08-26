"""Tests for the Selective Graph RAG integration inside AnswerUseCase.

Covers: _load_graph_context gating logic, _format_graph_context rendering,
and that knowledge_base_state is forwarded to both the initial and repair
ContextInputs calls when graph context is found.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.answer import (
    AnswerCommand,
    AnswerUseCase,
    _format_graph_context,
    _load_graph_context,
)
from app.application.queries.retrieve_evidence import RetrievalResult
from app.domain.enums import (
    ChunkType,
    GraphNodeType,
    MessageRole,
    MessageStatus,
    RelationshipType,
    RetrieverKind,
)
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.models.context_builder import ContextBuilder
from app.domain.models.entities import GenerationUsage
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.domain.documents.chunks import Chunk

# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_CONV_ID = uuid.uuid4()

_VALID_ANSWER_JSON = json.dumps({
    "answer": "Test answer.",
    "claims": [],
    "insufficient_evidence": True,
})

_BASE_CMD = AnswerCommand(
    scope=_SCOPE,
    conversation_id=_CONV_ID,
    query="Explain Newton's laws",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _chunk(*, chunk_id: uuid.UUID | None = None, doc_id: uuid.UUID | None = None) -> Chunk:
    return Chunk(
        id=chunk_id or uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        document_id=doc_id or uuid.uuid4(),
        chunk_type=ChunkType.TEXT,
        text=UntrustedText("Some passage text."),
        token_count=10,
        ordinal=0,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=_NOW,
    )


def _evidence(
    *,
    chunk_id: uuid.UUID | None = None,
    doc_id: uuid.UUID | None = None,
    label: int = 1,
) -> Evidence:
    return Evidence(
        label=EvidenceLabel(label),
        chunk=_chunk(chunk_id=chunk_id, doc_id=doc_id),
        retrievers=frozenset({RetrieverKind.DENSE}),
    )


def _entity(
    *,
    name: str = "Newton's Laws",
    source_chunk_id: uuid.UUID | None = None,
    entity_type: GraphNodeType = GraphNodeType.CONCEPT,
    description: str | None = None,
) -> GraphEntity:
    now = _NOW
    return GraphEntity(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        entity_type=entity_type,
        name=name,
        description=description,
        source_chunk_id=source_chunk_id,
        created_at=now,
        updated_at=now,
    )


def _rel(
    src_id: uuid.UUID,
    tgt_id: uuid.UUID,
    *,
    rel_type: RelationshipType = RelationshipType.RELATED_TO,
    page_number: int = 5,
) -> GraphRelationship:
    now = _NOW
    return GraphRelationship(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        source_entity_id=src_id,
        target_entity_id=tgt_id,
        relationship_type=rel_type,
        source_chunk_id=uuid.uuid4(),
        page_number=page_number,
        evidence=UntrustedText("evidence text"),
        created_at=now,
        updated_at=now,
    )


def _kb(*, graph_enabled: bool = True) -> MagicMock:
    kb = MagicMock()
    kb.graph_enabled = graph_enabled
    return kb


def _mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    repo.save_citations = AsyncMock()
    return repo


@asynccontextmanager
async def _uow(repo: AsyncMock | None = None) -> AsyncIterator[AsyncMock]:
    yield repo or _mock_repo()


class _FakeStream:
    def __init__(self, text: str) -> None:
        self._text = text
        self.usage: GenerationUsage | None = None

    async def __aiter__(self) -> AsyncIterator[str]:
        yield self._text


def _mock_gateway(response: str | None = None) -> MagicMock:
    chunk = response or _VALID_ANSWER_JSON
    gw = MagicMock()
    gw.generate_stream = MagicMock(side_effect=lambda _: _FakeStream(chunk))
    return gw


class _SpyContextBuilder:
    """Wraps a real ContextBuilder and records every ContextInputs it receives."""

    def __init__(self, real: ContextBuilder) -> None:
        self._real = real
        self.calls: list[object] = []

    def build(self, inputs: object) -> object:
        self.calls.append(inputs)
        return self._real.build(inputs)  # type: ignore[arg-type]

    def build_all(self, tasks: object) -> object:
        return self._real.build_all(tasks)  # type: ignore[arg-type]


def _real_context_builder() -> ContextBuilder:
    return ContextBuilder(lambda text: len(text.split()), token_budget=100_000)


def _make_use_case(
    *,
    evidence: list[Evidence] | None = None,
    kb_repo: AsyncMock | None = None,
    graph_repo: AsyncMock | None = None,
    spy: _SpyContextBuilder | None = None,
) -> AnswerUseCase:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(
        return_value=RetrievalResult(
            evidence=evidence or [],
            standalone_query=_BASE_CMD.query,
            was_rewritten=False,
        )
    )

    repo = _mock_repo()
    cb = spy or _real_context_builder()

    return AnswerUseCase(
        retrieve=retrieve,
        conversation_uow=lambda: _uow(repo),
        model_gateway=_mock_gateway(),
        context_builder=cb,  # type: ignore[arg-type]
        entailment=AsyncMock(),
        faithfulness=AsyncMock(),
        kb_repo=kb_repo,
        graph_repo=graph_repo,
    )


# ---------------------------------------------------------------------------
# _load_graph_context — gating logic
# ---------------------------------------------------------------------------


class TestLoadGraphContextGating:
    async def test_returns_none_when_kb_repo_not_wired(self) -> None:
        ev = _evidence()
        result = await _load_graph_context(_SCOPE, [ev], None, AsyncMock())
        assert result is None

    async def test_returns_none_when_graph_repo_not_wired(self) -> None:
        ev = _evidence()
        result = await _load_graph_context(_SCOPE, [ev], AsyncMock(), None)
        assert result is None

    async def test_returns_none_when_kb_not_found(self) -> None:
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=None)
        graph_repo = AsyncMock()

        result = await _load_graph_context(_SCOPE, [_evidence()], kb_repo, graph_repo)

        assert result is None
        graph_repo.list_entities_for_document.assert_not_awaited()

    async def test_returns_none_when_graph_disabled(self) -> None:
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=False))
        graph_repo = AsyncMock()

        result = await _load_graph_context(_SCOPE, [_evidence()], kb_repo, graph_repo)

        assert result is None
        graph_repo.list_entities_for_document.assert_not_awaited()

    async def test_returns_none_when_evidence_is_empty(self) -> None:
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()

        result = await _load_graph_context(_SCOPE, [], kb_repo, graph_repo)

        assert result is None
        graph_repo.list_entities_for_document.assert_not_awaited()

    async def test_returns_none_when_no_entity_matches_retrieved_chunks(self) -> None:
        chunk_id = uuid.uuid4()
        ev = _evidence(chunk_id=chunk_id)

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        # Entity belongs to a different chunk — not in the retrieved set.
        graph_repo.list_entities_for_document = AsyncMock(
            return_value=[_entity(source_chunk_id=uuid.uuid4())]
        )

        result = await _load_graph_context(_SCOPE, [ev], kb_repo, graph_repo)

        assert result is None
        graph_repo.concept_map_subgraph.assert_not_awaited()

    async def test_concept_map_subgraph_not_called_when_no_seeds(self) -> None:
        ev = _evidence()
        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        graph_repo.list_entities_for_document = AsyncMock(return_value=[])

        await _load_graph_context(_SCOPE, [ev], kb_repo, graph_repo)

        graph_repo.concept_map_subgraph.assert_not_awaited()


# ---------------------------------------------------------------------------
# _load_graph_context — happy path
# ---------------------------------------------------------------------------


class TestLoadGraphContextHappyPath:
    async def test_seeds_are_entities_whose_chunk_id_is_in_evidence(self) -> None:
        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        ev = _evidence(chunk_id=chunk_id, doc_id=doc_id)

        entity_a = _entity(name="Alpha", source_chunk_id=chunk_id)
        entity_b = _entity(name="Beta", source_chunk_id=uuid.uuid4())  # different chunk

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        graph_repo.list_entities_for_document = AsyncMock(return_value=[entity_a, entity_b])
        graph_repo.concept_map_subgraph = AsyncMock(return_value=([], []))

        await _load_graph_context(_SCOPE, [ev], kb_repo, graph_repo)

        call_args = graph_repo.concept_map_subgraph.call_args
        seed_ids: frozenset = call_args[0][1]
        assert entity_a.id in seed_ids
        assert entity_b.id not in seed_ids

    async def test_returns_formatted_string_when_subgraph_has_entities(self) -> None:
        chunk_id = uuid.uuid4()
        ev = _evidence(chunk_id=chunk_id)
        entity = _entity(name="Momentum", source_chunk_id=chunk_id)

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        graph_repo.list_entities_for_document = AsyncMock(return_value=[entity])
        graph_repo.concept_map_subgraph = AsyncMock(return_value=([entity], []))

        result = await _load_graph_context(_SCOPE, [ev], kb_repo, graph_repo)

        assert result is not None
        assert "Momentum" in result

    async def test_max_nodes_passed_to_subgraph(self) -> None:
        chunk_id = uuid.uuid4()
        ev = _evidence(chunk_id=chunk_id)
        entity = _entity(source_chunk_id=chunk_id)

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        graph_repo.list_entities_for_document = AsyncMock(return_value=[entity])
        graph_repo.concept_map_subgraph = AsyncMock(return_value=([entity], []))

        await _load_graph_context(_SCOPE, [ev], kb_repo, graph_repo)

        call_kwargs = graph_repo.concept_map_subgraph.call_args[1]
        assert "max_nodes" in call_kwargs
        assert call_kwargs["max_nodes"] == 30

    async def test_entities_queried_per_unique_document(self) -> None:
        doc_a = uuid.uuid4()
        doc_b = uuid.uuid4()
        ev1 = _evidence(doc_id=doc_a)
        ev2 = _evidence(doc_id=doc_b)

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        graph_repo.list_entities_for_document = AsyncMock(return_value=[])
        graph_repo.concept_map_subgraph = AsyncMock(return_value=([], []))

        await _load_graph_context(_SCOPE, [ev1, ev2], kb_repo, graph_repo)

        called_doc_ids = {
            call[0][1]  # second positional arg
            for call in graph_repo.list_entities_for_document.await_args_list
        }
        assert doc_a in called_doc_ids
        assert doc_b in called_doc_ids
        assert graph_repo.list_entities_for_document.await_count == 2


# ---------------------------------------------------------------------------
# _format_graph_context
# ---------------------------------------------------------------------------


class TestFormatGraphContext:
    def test_header_always_present(self) -> None:
        entity = _entity(name="Alpha")
        result = _format_graph_context([entity], [])
        assert "CONCEPT MAP" in result

    def test_entities_listed_alphabetically(self) -> None:
        e1 = _entity(name="Zebra")
        e2 = _entity(name="Alpha")
        result = _format_graph_context([e1, e2], [])
        assert result.index("Alpha") < result.index("Zebra")

    def test_entity_type_in_parentheses(self) -> None:
        e = _entity(name="Wave Function", entity_type=GraphNodeType.CONCEPT)
        result = _format_graph_context([e], [])
        assert "Wave Function (Concept)" in result

    def test_description_appended_when_present(self) -> None:
        e = _entity(name="Force", description="A push or pull")
        result = _format_graph_context([e], [])
        assert "Force (Concept): A push or pull" in result

    def test_no_relationship_section_when_empty(self) -> None:
        e = _entity(name="Alpha")
        result = _format_graph_context([e], [])
        assert "Relationships:" not in result

    def test_relationship_section_present_when_rels_exist(self) -> None:
        e1 = _entity(name="Alpha")
        e2 = _entity(name="Beta")
        rel = _rel(e1.id, e2.id, rel_type=RelationshipType.RELATED_TO, page_number=7)
        result = _format_graph_context([e1, e2], [rel])
        assert "Relationships:" in result

    def test_relationship_type_underscores_replaced_with_spaces(self) -> None:
        e1 = _entity(name="Alpha")
        e2 = _entity(name="Beta")
        rel = _rel(e1.id, e2.id, rel_type=RelationshipType.PREREQUISITE_OF)
        result = _format_graph_context([e1, e2], [rel])
        assert "PREREQUISITE OF" in result
        assert "PREREQUISITE_OF" not in result

    def test_relationship_includes_page_number(self) -> None:
        e1 = _entity(name="Alpha")
        e2 = _entity(name="Beta")
        rel = _rel(e1.id, e2.id, page_number=42)
        result = _format_graph_context([e1, e2], [rel])
        assert "p. 42" in result

    def test_relationship_uses_arrow_notation(self) -> None:
        e1 = _entity(name="Alpha")
        e2 = _entity(name="Beta")
        rel = _rel(e1.id, e2.id, rel_type=RelationshipType.RELATED_TO)
        result = _format_graph_context([e1, e2], [rel])
        assert "Alpha → RELATED TO → Beta" in result

    def test_relationship_with_unknown_endpoint_skipped(self) -> None:
        e1 = _entity(name="Alpha")
        rel = _rel(e1.id, uuid.uuid4())  # target not in entities list
        result = _format_graph_context([e1], [rel])
        assert "Relationships:" not in result


# ---------------------------------------------------------------------------
# integration — knowledge_base_state forwarded to ContextInputs
# ---------------------------------------------------------------------------


class TestGraphContextForwardedToContextInputs:
    async def test_knowledge_base_state_is_none_when_graph_not_wired(self) -> None:
        spy_cb = _SpyContextBuilder(_real_context_builder())
        uc = _make_use_case(evidence=[], spy=spy_cb)
        gen = await uc.execute(_BASE_CMD)
        async for _ in gen:
            pass

        assert spy_cb.calls
        # No graph repos wired → knowledge_base_state must be None.
        for inputs in spy_cb.calls:
            assert inputs.knowledge_base_state is None  # type: ignore[union-attr]

    async def test_knowledge_base_state_set_when_graph_wired_and_enabled(self) -> None:
        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        ev = _evidence(chunk_id=chunk_id, doc_id=doc_id)
        entity = _entity(name="Momentum", source_chunk_id=chunk_id)

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=True))
        graph_repo = AsyncMock()
        graph_repo.list_entities_for_document = AsyncMock(return_value=[entity])
        graph_repo.concept_map_subgraph = AsyncMock(return_value=([entity], []))

        spy_cb = _SpyContextBuilder(_real_context_builder())
        uc = _make_use_case(evidence=[ev], kb_repo=kb_repo, graph_repo=graph_repo, spy=spy_cb)
        gen = await uc.execute(_BASE_CMD)
        async for _ in gen:
            pass

        assert spy_cb.calls
        # The initial ContextInputs call should carry the graph context.
        initial_inputs = spy_cb.calls[0]
        assert initial_inputs.knowledge_base_state is not None  # type: ignore[union-attr]
        assert "Momentum" in initial_inputs.knowledge_base_state  # type: ignore[union-attr]

    async def test_knowledge_base_state_none_when_graph_disabled(self) -> None:
        chunk_id = uuid.uuid4()
        ev = _evidence(chunk_id=chunk_id)

        kb_repo = AsyncMock()
        kb_repo.get = AsyncMock(return_value=_kb(graph_enabled=False))
        graph_repo = AsyncMock()

        spy_cb = _SpyContextBuilder(_real_context_builder())
        uc = _make_use_case(evidence=[ev], kb_repo=kb_repo, graph_repo=graph_repo, spy=spy_cb)
        gen = await uc.execute(_BASE_CMD)
        async for _ in gen:
            pass

        for inputs in spy_cb.calls:
            assert inputs.knowledge_base_state is None  # type: ignore[union-attr]
