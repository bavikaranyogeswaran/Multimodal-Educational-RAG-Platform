"""Unit tests for GET /graph and GET /graph/entities/{id}.

All DB and auth dependencies are replaced via dependency_overrides so no
database is needed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.routers.graph import router as graph_router
from app.domain.enums import GraphNodeType, RelationshipType
from app.domain.errors import InvariantViolationError
from app.domain.graph.entities import GraphEntity, GraphRelationship
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _entity(
    *,
    name: str = "Momentum",
    entity_id: uuid.UUID | None = None,
    doc_id: uuid.UUID | None = None,
    chunk_id: uuid.UUID | None = None,
    entity_type: GraphNodeType = GraphNodeType.CONCEPT,
    description: str | None = None,
    page_number: int | None = 3,
) -> GraphEntity:
    eid = entity_id or uuid.uuid4()
    return GraphEntity(
        id=eid,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        entity_type=entity_type,
        name=name,
        description=description,
        source_document_id=doc_id,
        source_chunk_id=chunk_id,
        page_number=page_number,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _rel(
    src_id: uuid.UUID,
    tgt_id: uuid.UUID,
    *,
    rel_type: RelationshipType = RelationshipType.RELATED_TO,
    page_number: int = 5,
) -> GraphRelationship:
    return GraphRelationship(
        id=uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        source_entity_id=src_id,
        target_entity_id=tgt_id,
        relationship_type=rel_type,
        source_chunk_id=uuid.uuid4(),
        page_number=page_number,
        evidence=UntrustedText("Some evidence text."),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(
    session: AsyncMock,
    *,
    scope_raises_404: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_session] = _session_override(session)

    if scope_raises_404:
        def _missing() -> ScopeContext:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        app.dependency_overrides[get_kb_scope] = _missing
    else:
        app.dependency_overrides[get_kb_scope] = lambda: _SCOPE

    app.include_router(graph_router, prefix="/api/v1")
    return app


def _graph_url(*, document_id: uuid.UUID | None = None, max_nodes: int | None = None) -> str:
    url = f"/api/v1/knowledge-bases/{_KB_ID}/graph"
    params: list[str] = []
    if document_id:
        params.append(f"document_id={document_id}")
    if max_nodes is not None:
        params.append(f"max_nodes={max_nodes}")
    if params:
        url += "?" + "&".join(params)
    return url


def _entity_url(entity_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/graph/entities/{entity_id}"


class _MockResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _MockResult:
        return self

    def all(self) -> list:
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _session_for_queries(*result_sequences: list) -> AsyncMock:
    """Build a session whose execute() returns each list in order per call."""
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_MockResult(rows) for rows in result_sequences]
    )
    return session


# ---------------------------------------------------------------------------
# GET /graph
# ---------------------------------------------------------------------------


class TestGetGraph:
    def test_no_document_id_returns_empty_graph(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url())
        assert resp.status_code == 200
        body = resp.json()
        assert body["entities"] == []
        assert body["relationships"] == []

    def test_no_document_id_does_not_query_db(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session))
        client.get(_graph_url())
        session.execute.assert_not_called()

    def test_unknown_document_id_returns_empty_graph(self) -> None:
        session = _session_for_queries([])  # list_entities_for_document → empty
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=uuid.uuid4()))
        assert resp.status_code == 200
        assert resp.json()["entities"] == []

    def test_returns_entities_and_relationships(self) -> None:
        doc_id = uuid.uuid4()
        e1 = _entity(name="Alpha", doc_id=doc_id)
        e2 = _entity(name="Beta", doc_id=doc_id)
        rel = _rel(e1.id, e2.id)

        from app.infrastructure.database.models.graph import (
            GraphEntityModel,
            GraphRelationshipModel,
        )

        def _entity_model(e: GraphEntity) -> MagicMock:
            m = MagicMock(spec=GraphEntityModel)
            m.id = e.id
            m.user_id = e.user_id
            m.knowledge_base_id = e.knowledge_base_id
            m.entity_type = e.entity_type.value
            m.name = e.name
            m.description = e.description
            m.source_document_id = e.source_document_id
            m.source_chunk_id = e.source_chunk_id
            m.page_number = e.page_number
            m.created_at = e.created_at
            m.updated_at = e.updated_at
            return m

        def _rel_model(r: GraphRelationship) -> MagicMock:
            m = MagicMock(spec=GraphRelationshipModel)
            m.id = r.id
            m.user_id = r.user_id
            m.knowledge_base_id = r.knowledge_base_id
            m.source_entity_id = r.source_entity_id
            m.target_entity_id = r.target_entity_id
            m.relationship_type = r.relationship_type.value
            m.source_chunk_id = r.source_chunk_id
            m.page_number = r.page_number
            m.evidence = r.evidence.value
            m.weight = r.weight
            m.extraction_confidence = r.extraction_confidence
            m.created_at = r.created_at
            m.updated_at = r.updated_at
            return m

        session = _session_for_queries(
            [_entity_model(e1), _entity_model(e2)],  # list_entities_for_document
            [e1.id, e2.id],                          # bounded walk — ids, not rows
            [_entity_model(e1), _entity_model(e2)],  # entity load for the bounded set
            [_rel_model(rel)],                       # edges inside the bounded set
        )
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=doc_id))
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["entities"]) == 2
        assert len(body["relationships"]) == 1
        names = {e["name"] for e in body["entities"]}
        assert names == {"Alpha", "Beta"}

    def test_entity_response_shape(self) -> None:
        doc_id = uuid.uuid4()
        entity = _entity(name="Force", description="A push or pull", doc_id=doc_id)

        from app.infrastructure.database.models.graph import GraphEntityModel
        m = MagicMock(spec=GraphEntityModel)
        m.id = entity.id
        m.user_id = entity.user_id
        m.knowledge_base_id = entity.knowledge_base_id
        m.entity_type = entity.entity_type.value
        m.name = entity.name
        m.description = entity.description
        m.source_document_id = entity.source_document_id
        m.source_chunk_id = entity.source_chunk_id
        m.page_number = entity.page_number
        m.created_at = entity.created_at
        m.updated_at = entity.updated_at

        # seed list, bounded walk (ids), entity load, edges
        session = _session_for_queries([m], [entity.id], [m], [])
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=doc_id))
        assert resp.status_code == 200
        body = resp.json()
        ent_body = body["entities"][0]
        assert ent_body["name"] == "Force"
        assert ent_body["description"] == "A push or pull"
        assert ent_body["entity_type"] == "Concept"
        assert ent_body["page_number"] == entity.page_number

    def test_relationship_response_shape(self) -> None:
        doc_id = uuid.uuid4()
        e1 = _entity(name="Alpha", doc_id=doc_id)
        e2 = _entity(name="Beta", doc_id=doc_id)
        rel = _rel(e1.id, e2.id, rel_type=RelationshipType.PREREQUISITE_OF, page_number=7)

        from app.infrastructure.database.models.graph import (
            GraphEntityModel,
            GraphRelationshipModel,
        )

        def _em(e: GraphEntity) -> MagicMock:
            m = MagicMock(spec=GraphEntityModel)
            m.id = e.id
            m.user_id = e.user_id
            m.knowledge_base_id = e.knowledge_base_id
            m.entity_type = e.entity_type.value
            m.name = e.name
            m.description = e.description
            m.source_document_id = e.source_document_id
            m.source_chunk_id = e.source_chunk_id
            m.page_number = e.page_number
            m.created_at = e.created_at
            m.updated_at = e.updated_at
            return m

        rm = MagicMock(spec=GraphRelationshipModel)
        rm.id = rel.id
        rm.user_id = rel.user_id
        rm.knowledge_base_id = rel.knowledge_base_id
        rm.source_entity_id = rel.source_entity_id
        rm.target_entity_id = rel.target_entity_id
        rm.relationship_type = rel.relationship_type.value
        rm.source_chunk_id = rel.source_chunk_id
        rm.page_number = rel.page_number
        rm.evidence = rel.evidence.value
        rm.weight = rel.weight
        rm.extraction_confidence = rel.extraction_confidence
        rm.created_at = rel.created_at
        rm.updated_at = rel.updated_at

        session = _session_for_queries(
            [_em(e1), _em(e2)], [e1.id, e2.id], [_em(e1), _em(e2)], [rm]
        )
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=doc_id))
        body = resp.json()
        r = body["relationships"][0]
        assert r["relationship_type"] == "PREREQUISITE_OF"
        assert r["page_number"] == 7
        assert r["source_entity_id"] == str(e1.id)
        assert r["target_entity_id"] == str(e2.id)
        assert r["evidence"] == "Some evidence text."

    def test_max_nodes_param_accepted(self) -> None:
        session = _session_for_queries([])
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=uuid.uuid4(), max_nodes=50))
        assert resp.status_code == 200

    def test_max_nodes_above_upper_bound_rejected(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=uuid.uuid4(), max_nodes=201))
        assert resp.status_code == 422

    def test_max_nodes_zero_rejected(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session))
        resp = client.get(_graph_url(document_id=uuid.uuid4(), max_nodes=0))
        assert resp.status_code == 422

    def test_missing_kb_returns_404(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session, scope_raises_404=True))
        resp = client.get(_graph_url())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /graph/entities/{entity_id}
# ---------------------------------------------------------------------------


class TestGetGraphEntity:
    def test_unknown_entity_returns_404(self) -> None:
        session = _session_for_queries([])  # get_entity → None
        client = TestClient(_make_app(session))
        resp = client.get(_entity_url(uuid.uuid4()))
        assert resp.status_code == 404

    def test_returns_entity_and_relationships(self) -> None:
        entity = _entity(name="Newton's Laws")
        other = _entity(name="Momentum")
        rel = _rel(entity.id, other.id)

        from app.infrastructure.database.models.graph import (
            GraphEntityModel,
            GraphRelationshipModel,
        )

        def _em(e: GraphEntity) -> MagicMock:
            m = MagicMock(spec=GraphEntityModel)
            m.id = e.id
            m.user_id = e.user_id
            m.knowledge_base_id = e.knowledge_base_id
            m.entity_type = e.entity_type.value
            m.name = e.name
            m.description = e.description
            m.source_document_id = e.source_document_id
            m.source_chunk_id = e.source_chunk_id
            m.page_number = e.page_number
            m.created_at = e.created_at
            m.updated_at = e.updated_at
            return m

        rm = MagicMock(spec=GraphRelationshipModel)
        rm.id = rel.id
        rm.user_id = rel.user_id
        rm.knowledge_base_id = rel.knowledge_base_id
        rm.source_entity_id = rel.source_entity_id
        rm.target_entity_id = rel.target_entity_id
        rm.relationship_type = rel.relationship_type.value
        rm.source_chunk_id = rel.source_chunk_id
        rm.page_number = rel.page_number
        rm.evidence = rel.evidence.value
        rm.weight = rel.weight
        rm.extraction_confidence = rel.extraction_confidence
        rm.created_at = rel.created_at
        rm.updated_at = rel.updated_at

        session = _session_for_queries([_em(entity)], [rm])
        client = TestClient(_make_app(session))
        resp = client.get(_entity_url(entity.id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["entity"]["name"] == "Newton's Laws"
        assert len(body["relationships"]) == 1
        assert body["relationships"][0]["source_entity_id"] == str(entity.id)

    def test_entity_with_no_relationships_returns_empty_list(self) -> None:
        entity = _entity(name="Alpha")

        from app.infrastructure.database.models.graph import GraphEntityModel
        m = MagicMock(spec=GraphEntityModel)
        m.id = entity.id
        m.user_id = entity.user_id
        m.knowledge_base_id = entity.knowledge_base_id
        m.entity_type = entity.entity_type.value
        m.name = entity.name
        m.description = entity.description
        m.source_document_id = entity.source_document_id
        m.source_chunk_id = entity.source_chunk_id
        m.page_number = entity.page_number
        m.created_at = entity.created_at
        m.updated_at = entity.updated_at

        session = _session_for_queries([m], [])
        client = TestClient(_make_app(session))
        resp = client.get(_entity_url(entity.id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["relationships"] == []

    def test_response_contains_all_entity_fields(self) -> None:
        entity = _entity(
            name="Wave Function",
            entity_type=GraphNodeType.CONCEPT,
            description="A probability amplitude",
            page_number=12,
        )

        from app.infrastructure.database.models.graph import GraphEntityModel
        m = MagicMock(spec=GraphEntityModel)
        m.id = entity.id
        m.user_id = entity.user_id
        m.knowledge_base_id = entity.knowledge_base_id
        m.entity_type = entity.entity_type.value
        m.name = entity.name
        m.description = entity.description
        m.source_document_id = entity.source_document_id
        m.source_chunk_id = entity.source_chunk_id
        m.page_number = entity.page_number
        m.created_at = entity.created_at
        m.updated_at = entity.updated_at

        session = _session_for_queries([m], [])
        client = TestClient(_make_app(session))
        resp = client.get(_entity_url(entity.id))
        ent = resp.json()["entity"]
        assert ent["name"] == "Wave Function"
        assert ent["entity_type"] == "Concept"
        assert ent["description"] == "A probability amplitude"
        assert ent["page_number"] == 12

    def test_missing_kb_returns_404(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session, scope_raises_404=True))
        resp = client.get(_entity_url(uuid.uuid4()))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /graph/entities/{id}/prerequisites
# ---------------------------------------------------------------------------


def _entity_model(e: GraphEntity) -> MagicMock:
    """A row shaped like the ORM model, for a session that never touches a database."""
    from app.infrastructure.database.models.graph import GraphEntityModel

    m = MagicMock(spec=GraphEntityModel)
    m.id = e.id
    m.user_id = e.user_id
    m.knowledge_base_id = e.knowledge_base_id
    m.entity_type = e.entity_type.value
    m.name = e.name
    m.description = e.description
    m.source_document_id = e.source_document_id
    m.source_chunk_id = e.source_chunk_id
    m.page_number = e.page_number
    m.created_at = e.created_at
    m.updated_at = e.updated_at
    return m


def _rel_model(r: GraphRelationship) -> MagicMock:
    from app.infrastructure.database.models.graph import GraphRelationshipModel

    m = MagicMock(spec=GraphRelationshipModel)
    m.id = r.id
    m.user_id = r.user_id
    m.knowledge_base_id = r.knowledge_base_id
    m.source_entity_id = r.source_entity_id
    m.target_entity_id = r.target_entity_id
    m.relationship_type = r.relationship_type.value
    m.source_chunk_id = r.source_chunk_id
    m.page_number = r.page_number
    m.evidence = r.evidence.value
    m.weight = r.weight
    m.extraction_confidence = r.extraction_confidence
    m.created_at = r.created_at
    m.updated_at = r.updated_at
    return m


def _prereq_url(entity_id: uuid.UUID) -> str:
    return f"{_entity_url(entity_id)}/prerequisites"


def _related_url(entity_id: uuid.UUID) -> str:
    return f"{_entity_url(entity_id)}/related"


class TestPrerequisiteView:
    def test_splits_edges_by_direction(self) -> None:
        """`A PREREQUISITE_OF B` puts A before B, so the direction decides the list."""
        subject = _entity(name="Integration")
        needed = _entity(name="Differentiation")
        unlocked = _entity(name="Differential Equations")

        # needed -> subject, and subject -> unlocked
        rels = [
            _rel(needed.id, subject.id, rel_type=RelationshipType.PREREQUISITE_OF),
            _rel(subject.id, unlocked.id, rel_type=RelationshipType.PREREQUISITE_OF),
        ]

        session = _session_for_queries(
            [_entity_model(subject)],                        # get_entity
            [_rel_model(r) for r in rels],                   # typed edges
            [_entity_model(needed), _entity_model(unlocked)],  # neighbour entities
        )
        resp = TestClient(_make_app(session)).get(_prereq_url(subject.id))

        assert resp.status_code == 200
        body = resp.json()
        assert [e["name"] for e in body["prerequisites"]] == ["Differentiation"]
        assert [e["name"] for e in body["unlocks"]] == ["Differential Equations"]

    def test_carries_the_edges_so_every_claim_has_a_source(self) -> None:
        """A bare list of names would be the model's opinion presented as fact."""
        subject = _entity(name="Integration")
        needed = _entity(name="Differentiation")
        rel = _rel(needed.id, subject.id, rel_type=RelationshipType.PREREQUISITE_OF)

        session = _session_for_queries(
            [_entity_model(subject)],
            [_rel_model(rel)],
            [_entity_model(needed)],
        )
        resp = TestClient(_make_app(session)).get(_prereq_url(subject.id))

        edges = resp.json()["relationships"]
        assert len(edges) == 1
        assert edges[0]["page_number"] == rel.page_number
        assert edges[0]["evidence"] == "Some evidence text."

    def test_entity_with_no_prerequisites_returns_empty_lists(self) -> None:
        subject = _entity(name="Arithmetic")
        session = _session_for_queries([_entity_model(subject)], [], [])
        resp = TestClient(_make_app(session)).get(_prereq_url(subject.id))

        body = resp.json()
        assert body["prerequisites"] == []
        assert body["unlocks"] == []
        assert body["entity"]["name"] == "Arithmetic"

    def test_unknown_entity_returns_404(self) -> None:
        session = _session_for_queries([])
        resp = TestClient(_make_app(session)).get(_prereq_url(uuid.uuid4()))
        assert resp.status_code == 404

    def test_missing_kb_returns_404(self) -> None:
        client = TestClient(_make_app(AsyncMock(), scope_raises_404=True))
        assert client.get(_prereq_url(uuid.uuid4())).status_code == 404


# ---------------------------------------------------------------------------
# GET /graph/entities/{id}/related
# ---------------------------------------------------------------------------


class TestRelatedView:
    def test_reports_the_other_endpoint_whichever_end_the_edge_started(self) -> None:
        """Association reads the same both ways, unlike a prerequisite."""
        subject = _entity(name="Momentum")
        outgoing = _entity(name="Impulse")
        incoming = _entity(name="Energy")

        rels = [
            _rel(subject.id, outgoing.id, rel_type=RelationshipType.RELATED_TO),
            _rel(incoming.id, subject.id, rel_type=RelationshipType.COMPARES_WITH),
        ]

        session = _session_for_queries(
            [_entity_model(subject)],
            [_rel_model(r) for r in rels],
            [_entity_model(incoming), _entity_model(outgoing)],
        )
        resp = TestClient(_make_app(session)).get(_related_url(subject.id))

        assert resp.status_code == 200
        names = {e["name"] for e in resp.json()["related"]}
        assert names == {"Impulse", "Energy"}

    def test_the_view_never_has_to_exclude_the_subject_itself(self) -> None:
        """Why the endpoint takes the opposite endpoint without checking for the subject.

        A concept cannot be related to itself: the entity refuses a self-link at
        construction, so no such row can reach the view to be filtered out. Guarding
        against it in the endpoint would be defending a case the domain has already
        made unrepresentable — and this test is what keeps that true.
        """
        subject_id = uuid.uuid4()
        with pytest.raises(InvariantViolationError):
            _rel(subject_id, subject_id, rel_type=RelationshipType.RELATED_TO)

    def test_entity_with_no_associations_returns_empty(self) -> None:
        subject = _entity(name="Isolated")
        session = _session_for_queries([_entity_model(subject)], [], [])
        resp = TestClient(_make_app(session)).get(_related_url(subject.id))

        assert resp.json()["related"] == []
        assert resp.json()["entity"]["name"] == "Isolated"

    def test_unknown_entity_returns_404(self) -> None:
        session = _session_for_queries([])
        resp = TestClient(_make_app(session)).get(_related_url(uuid.uuid4()))
        assert resp.status_code == 404

    def test_missing_kb_returns_404(self) -> None:
        client = TestClient(_make_app(AsyncMock(), scope_raises_404=True))
        assert client.get(_related_url(uuid.uuid4())).status_code == 404
