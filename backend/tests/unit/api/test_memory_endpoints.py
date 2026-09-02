"""Unit tests for GET/PATCH/DELETE /knowledge-bases/{kb_id}/memory.

All DB and auth dependencies are replaced via dependency_overrides — no
database is needed. The session mock is wired to return MemoryFactModel
instances directly.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.routers.memory import router as memory_router
from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.conversation import MemoryFactModel
from app.infrastructure.database.session import get_session

_NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_model(
    *,
    fact_id: uuid.UUID | None = None,
    key: str = "exam_date",
    status: str = MemoryStatus.ACTIVE.value,
    expires_at: datetime | None = None,
) -> MemoryFactModel:
    return MemoryFactModel(
        id=fact_id or uuid.uuid4(),
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        memory_type=MemoryType.EXAM_DATE.value,
        key=key,
        value={"date": "2026-12-01"},
        confidence=0.9,
        provenance=int(MemoryProvenance.USER_STATEMENT),
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
        expires_at=expires_at,
    )


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
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_MockResult(rows) for rows in result_sequences]
    )
    session.merge = AsyncMock()
    return session


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

    app.include_router(memory_router, prefix="/api/v1")
    return app


def _list_url() -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/memory"


def _fact_url(fact_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/memory/{fact_id}"


# ---------------------------------------------------------------------------
# GET /memory
# ---------------------------------------------------------------------------


class TestListMemory:
    def test_returns_200_with_empty_list(self) -> None:
        session = _session_for_queries([])
        client = TestClient(_make_app(session))
        resp = client.get(_list_url())
        assert resp.status_code == 200
        assert resp.json() == {"facts": []}

    def test_returns_active_facts(self) -> None:
        model = _make_model(key="exam_date")
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.get(_list_url())
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["facts"]) == 1
        assert body["facts"][0]["key"] == "exam_date"

    def test_response_shape(self) -> None:
        model = _make_model()
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.get(_list_url())
        fact = resp.json()["facts"][0]
        for field in ("id", "key", "value", "confidence", "provenance", "status",
                      "memory_type", "created_at", "updated_at"):
            assert field in fact, f"missing field: {field}"

    def test_multiple_facts_returned(self) -> None:
        models = [_make_model(key=f"k{i}") for i in range(3)]
        session = _session_for_queries(models)
        client = TestClient(_make_app(session))
        resp = client.get(_list_url())
        assert len(resp.json()["facts"]) == 3

    def test_missing_kb_returns_404(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session, scope_raises_404=True))
        resp = client.get(_list_url())
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /memory/{id}
# ---------------------------------------------------------------------------


class TestUpdateMemory:
    def test_dispute_active_fact_returns_200(self) -> None:
        fact_id = uuid.uuid4()
        model = _make_model(fact_id=fact_id, status=MemoryStatus.ACTIVE.value)
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.patch(_fact_url(fact_id), json={"status": "DISPUTED"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "DISPUTED"

    def test_delete_active_fact_returns_200(self) -> None:
        fact_id = uuid.uuid4()
        model = _make_model(fact_id=fact_id, status=MemoryStatus.ACTIVE.value)
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.patch(_fact_url(fact_id), json={"status": "DELETED"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "DELETED"

    def test_unknown_fact_returns_404(self) -> None:
        session = _session_for_queries([])  # get → None
        client = TestClient(_make_app(session))
        resp = client.patch(_fact_url(uuid.uuid4()), json={"status": "DELETED"})
        assert resp.status_code == 404

    def test_invalid_status_value_returns_422(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session))
        resp = client.patch(_fact_url(uuid.uuid4()), json={"status": "ACTIVE"})
        assert resp.status_code == 422

    def test_invalid_transition_returns_409(self) -> None:
        fact_id = uuid.uuid4()
        # An already-DELETED fact cannot be deleted again — mark_deleted raises InvariantViolationError
        model = _make_model(fact_id=fact_id, status=MemoryStatus.DELETED.value)
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.patch(_fact_url(fact_id), json={"status": "DELETED"})
        assert resp.status_code == 409

    def test_missing_kb_returns_404(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session, scope_raises_404=True))
        resp = client.patch(_fact_url(uuid.uuid4()), json={"status": "DELETED"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /memory/{id}
# ---------------------------------------------------------------------------


class TestDeleteMemory:
    def test_delete_active_fact_returns_204(self) -> None:
        fact_id = uuid.uuid4()
        model = _make_model(fact_id=fact_id, status=MemoryStatus.ACTIVE.value)
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.delete(_fact_url(fact_id))
        assert resp.status_code == 204
        assert resp.content == b""

    def test_unknown_fact_returns_404(self) -> None:
        session = _session_for_queries([])
        client = TestClient(_make_app(session))
        resp = client.delete(_fact_url(uuid.uuid4()))
        assert resp.status_code == 404

    def test_invalid_transition_returns_409(self) -> None:
        fact_id = uuid.uuid4()
        # An already-DELETED fact cannot be deleted again
        model = _make_model(fact_id=fact_id, status=MemoryStatus.DELETED.value)
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        resp = client.delete(_fact_url(fact_id))
        assert resp.status_code == 409

    def test_merge_called_after_delete(self) -> None:
        fact_id = uuid.uuid4()
        model = _make_model(fact_id=fact_id, status=MemoryStatus.ACTIVE.value)
        session = _session_for_queries([model])
        client = TestClient(_make_app(session))
        client.delete(_fact_url(fact_id))
        session.merge.assert_awaited_once()

    def test_missing_kb_returns_404(self) -> None:
        session = AsyncMock()
        client = TestClient(_make_app(session, scope_raises_404=True))
        resp = client.delete(_fact_url(uuid.uuid4()))
        assert resp.status_code == 404
