"""Unit tests for the Knowledge Base CRUD router.

All DB and auth dependencies are replaced via dependency_overrides so no real
database or JWT service is needed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.scope import get_kb_scope
from app.api.routers.knowledge_bases import router
from app.domain.enums import ExplanationLevel
from app.domain.knowledge_base.entities import KnowledgeBase
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2024, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _kb(user_id: UUID, *, name: str = "Test KB") -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        user_id=user_id,
        name=name,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _session_for_write() -> AsyncMock:
    """Session mock suitable for POST/PATCH/DELETE: merge + commit."""
    return AsyncMock()


def _session_for_list(rows: list) -> AsyncMock:
    """Session mock that returns `rows` from execute().scalars().all()."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _session_for_get(row) -> AsyncMock:
    """Session mock that returns `row` from execute().scalar_one_or_none()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _make_app(
    user_id: UUID,
    session: AsyncMock,
    *,
    scope: ScopeContext | None = None,
    scope_raises_404: bool = False,
    auth_raises_401: bool = False,
) -> FastAPI:
    test_app = FastAPI()

    if auth_raises_401:

        def _unauthed() -> UUID:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        test_app.dependency_overrides[get_current_user] = _unauthed
    else:
        test_app.dependency_overrides[get_current_user] = lambda: user_id

    test_app.dependency_overrides[get_session] = _session_override(session)

    if scope_raises_404:

        def _missing() -> ScopeContext:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        test_app.dependency_overrides[get_kb_scope] = _missing
    elif scope is not None:
        test_app.dependency_overrides[get_kb_scope] = lambda: scope

    test_app.include_router(router, prefix="/api/v1")
    return test_app


# ---------------------------------------------------------------------------
# POST /api/v1/knowledge-bases
# ---------------------------------------------------------------------------


class TestCreateKnowledgeBase:
    def test_returns_201_with_valid_request(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(_make_app(user_id, _session_for_write())) as client:
            response = client.post(
                "/api/v1/knowledge-bases",
                json={"name": "Maths A-Level"},
            )
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Maths A-Level"
        assert body["user_id"] == str(user_id)
        uuid.UUID(body["id"])

    def test_response_includes_timestamps(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(_make_app(user_id, _session_for_write())) as client:
            response = client.post(
                "/api/v1/knowledge-bases",
                json={"name": "Chemistry"},
            )
        assert response.status_code == 201
        body = response.json()
        assert "created_at" in body
        assert "updated_at" in body

    def test_optional_fields_default_correctly(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(_make_app(user_id, _session_for_write())) as client:
            response = client.post(
                "/api/v1/knowledge-bases",
                json={"name": "Physics"},
            )
        body = response.json()
        assert body["preferred_language"] == "en"
        assert body["explanation_level"] == ExplanationLevel.INTERMEDIATE.value
        assert body["graph_enabled"] is False

    def test_returns_422_when_name_is_missing(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(_make_app(user_id, _session_for_write())) as client:
            response = client.post("/api/v1/knowledge-bases", json={})
        assert response.status_code == 422

    def test_returns_401_when_no_token(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(
            _make_app(user_id, _session_for_write(), auth_raises_401=True)
        ) as client:
            response = client.post(
                "/api/v1/knowledge-bases",
                json={"name": "Unauthorised"},
            )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/knowledge-bases
# ---------------------------------------------------------------------------


class TestListKnowledgeBases:
    def test_returns_200_with_users_kbs(self) -> None:
        user_id = uuid.uuid4()
        kbs = [_kb(user_id, name="KB A"), _kb(user_id, name="KB B")]
        with TestClient(_make_app(user_id, _session_for_list(kbs))) as client:
            response = client.get("/api/v1/knowledge-bases")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 2
        assert {item["name"] for item in body} == {"KB A", "KB B"}

    def test_list_only_contains_requesting_users_kbs(self) -> None:
        user_a = uuid.uuid4()
        kb_a = _kb(user_a, name="User A KB")
        with TestClient(_make_app(user_a, _session_for_list([kb_a]))) as client:
            response = client.get("/api/v1/knowledge-bases")
        body = response.json()
        assert all(item["user_id"] == str(user_a) for item in body)

    def test_returns_empty_list_when_user_has_no_kbs(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(_make_app(user_id, _session_for_list([]))) as client:
            response = client.get("/api/v1/knowledge-bases")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_401_when_no_token(self) -> None:
        user_id = uuid.uuid4()
        with TestClient(
            _make_app(user_id, _session_for_list([]), auth_raises_401=True)
        ) as client:
            response = client.get("/api/v1/knowledge-bases")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/knowledge-bases/{kb_id}
# ---------------------------------------------------------------------------


class TestGetKnowledgeBase:
    def test_returns_200_for_own_kb(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
        kb = _kb(user_id, name="My KB")
        session = _session_for_get(kb)
        with TestClient(_make_app(user_id, session, scope=scope)) as client:
            response = client.get(f"/api/v1/knowledge-bases/{kb_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "My KB"

    def test_returns_404_for_foreign_kb(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session = _session_for_write()
        with TestClient(
            _make_app(user_id, session, scope_raises_404=True)
        ) as client:
            response = client.get(f"/api/v1/knowledge-bases/{kb_id}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/knowledge-bases/{kb_id}
# ---------------------------------------------------------------------------


class TestUpdateKnowledgeBase:
    def test_returns_200_with_updated_name(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
        existing_kb = _kb(user_id, name="Old Name")
        # get() returns existing_kb; save + commit use the same mock
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_kb
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)

        with TestClient(_make_app(user_id, session, scope=scope)) as client:
            response = client.patch(
                f"/api/v1/knowledge-bases/{kb_id}",
                json={"name": "New Name"},
            )
        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_patch_is_partial_other_fields_unchanged(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
        existing_kb = _kb(user_id, name="Keep This")
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing_kb
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)

        with TestClient(_make_app(user_id, session, scope=scope)) as client:
            response = client.patch(
                f"/api/v1/knowledge-bases/{kb_id}",
                json={"subject": "Mathematics"},
            )
        assert response.status_code == 200
        assert response.json()["name"] == "Keep This"
        assert response.json()["subject"] == "Mathematics"

    def test_returns_404_for_foreign_kb(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session = _session_for_write()
        with TestClient(
            _make_app(user_id, session, scope_raises_404=True)
        ) as client:
            response = client.patch(
                f"/api/v1/knowledge-bases/{kb_id}",
                json={"name": "Stolen Update"},
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/knowledge-bases/{kb_id}
# ---------------------------------------------------------------------------


class TestDeleteKnowledgeBase:
    def test_returns_204_on_success(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        scope = ScopeContext(user_id=user_id, knowledge_base_id=kb_id)
        session = _session_for_write()
        with TestClient(_make_app(user_id, session, scope=scope)) as client:
            response = client.delete(f"/api/v1/knowledge-bases/{kb_id}")
        assert response.status_code == 204
        assert response.content == b""

    def test_returns_404_for_foreign_kb(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session = _session_for_write()
        with TestClient(
            _make_app(user_id, session, scope_raises_404=True)
        ) as client:
            response = client.delete(f"/api/v1/knowledge-bases/{kb_id}")
        assert response.status_code == 404

    @pytest.mark.parametrize("method,path_suffix,payload", [
        ("GET", "", None),
        ("POST", "", {"name": "X"}),
    ])
    def test_returns_401_for_unauthenticated_non_scoped_endpoints(
        self, method: str, path_suffix: str, payload: dict | None
    ) -> None:
        user_id = uuid.uuid4()
        session = _session_for_write()
        with TestClient(
            _make_app(user_id, session, auth_raises_401=True)
        ) as client:
            url = f"/api/v1/knowledge-bases{path_suffix}"
            response = client.request(method, url, json=payload)
        assert response.status_code == 401
