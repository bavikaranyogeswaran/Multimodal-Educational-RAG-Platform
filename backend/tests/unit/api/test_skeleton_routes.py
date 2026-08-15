"""Tests for the Phase 3.6 skeleton routes.

Verifies that every stub endpoint is reachable at its final URL and returns 501,
and that auth + scope guards are active (no token → 401, foreign KB → 404).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.scope import get_kb_scope
from app.api.routers.conversations import router as conversations_router
from app.api.routers.documents import router as documents_router
from app.api.routers.graph import router as graph_router
from app.api.routers.memory import router as memory_router
from app.api.routers.study_content import router as study_content_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(
    *routers,
    user_id: uuid.UUID,
    kb_id: uuid.UUID,
    auth_raises_401: bool = False,
    scope_raises_404: bool = False,
) -> FastAPI:
    test_app = FastAPI()

    if auth_raises_401:

        def _unauthed() -> uuid.UUID:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        test_app.dependency_overrides[get_current_user] = _unauthed
    else:
        test_app.dependency_overrides[get_current_user] = lambda: user_id

    test_app.dependency_overrides[get_session] = _session_override(AsyncMock())

    if scope_raises_404:

        def _missing() -> ScopeContext:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        test_app.dependency_overrides[get_kb_scope] = _missing
    elif not auth_raises_401:
        test_app.dependency_overrides[get_kb_scope] = lambda: ScopeContext(
            user_id=user_id, knowledge_base_id=kb_id
        )

    for router in routers:
        test_app.include_router(router, prefix="/api/v1")

    return test_app


# ---------------------------------------------------------------------------
# Conversations router — primary test required by the PLAN
# ---------------------------------------------------------------------------


class TestConversationSkeletons:
    def test_list_conversations_returns_501_with_valid_token(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(conversations_router, user_id=user_id, kb_id=kb_id)
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/knowledge-bases/{kb_id}/conversations")
        assert resp.status_code == 501
        assert resp.json() == {"detail": "Not implemented", "phase": "9"}

    def test_list_conversations_returns_401_without_token(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(
            conversations_router, user_id=user_id, kb_id=kb_id, auth_raises_401=True
        )
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/knowledge-bases/{kb_id}/conversations")
        assert resp.status_code == 401

    def test_list_conversations_returns_404_for_foreign_kb(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(
            conversations_router, user_id=user_id, kb_id=kb_id, scope_raises_404=True
        )
        with TestClient(app) as client:
            resp = client.get(f"/api/v1/knowledge-bases/{kb_id}/conversations")
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        "method,path_suffix",
        [
            ("POST", ""),
            ("GET", ""),
            ("GET", f"/{uuid.uuid4()}"),
            ("POST", f"/{uuid.uuid4()}/stream"),
            ("GET", f"/{uuid.uuid4()}/messages"),
        ],
    )
    def test_all_conversation_endpoints_return_501(
        self, method: str, path_suffix: str
    ) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(conversations_router, user_id=user_id, kb_id=kb_id)
        with TestClient(app) as client:
            resp = client.request(
                method, f"/api/v1/knowledge-bases/{kb_id}/conversations{path_suffix}"
            )
        assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Documents router
# ---------------------------------------------------------------------------


class TestDocumentSkeletons:
    def test_delete_document_returns_501(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        app = _make_app(documents_router, user_id=user_id, kb_id=kb_id)
        with TestClient(app) as client:
            resp = client.delete(f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}")
        assert resp.status_code == 501
        assert resp.json()["phase"] == "4"

    def test_documents_returns_401_without_token(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(
            documents_router, user_id=user_id, kb_id=kb_id, auth_raises_401=True
        )
        with TestClient(app) as client:
            resp = client.post(f"/api/v1/knowledge-bases/{kb_id}/documents")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Graph router
# ---------------------------------------------------------------------------


class TestGraphSkeletons:
    @pytest.mark.parametrize(
        "method,path_suffix",
        [
            ("GET", ""),
            ("GET", f"/entities/{uuid.uuid4()}"),
        ],
    )
    def test_all_graph_endpoints_return_501(
        self, method: str, path_suffix: str
    ) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(graph_router, user_id=user_id, kb_id=kb_id)
        with TestClient(app) as client:
            resp = client.request(
                method, f"/api/v1/knowledge-bases/{kb_id}/graph{path_suffix}"
            )
        assert resp.status_code == 501
        assert resp.json()["phase"] == "12"


# ---------------------------------------------------------------------------
# Memory router
# ---------------------------------------------------------------------------


class TestMemorySkeletons:
    @pytest.mark.parametrize(
        "method,path_suffix",
        [
            ("GET", ""),
            ("PATCH", f"/{uuid.uuid4()}"),
            ("DELETE", f"/{uuid.uuid4()}"),
        ],
    )
    def test_all_memory_endpoints_return_501(
        self, method: str, path_suffix: str
    ) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(memory_router, user_id=user_id, kb_id=kb_id)
        with TestClient(app) as client:
            resp = client.request(
                method, f"/api/v1/knowledge-bases/{kb_id}/memory{path_suffix}"
            )
        assert resp.status_code == 501
        assert resp.json()["phase"] == "14"


# ---------------------------------------------------------------------------
# Study content router
# ---------------------------------------------------------------------------


class TestStudyContentSkeletons:
    @pytest.mark.parametrize(
        "method,path_suffix",
        [
            ("POST", "/summaries"),
            ("GET", "/summaries"),
            ("POST", "/quizzes"),
            ("GET", f"/quizzes/{uuid.uuid4()}"),
            ("POST", f"/quizzes/{uuid.uuid4()}/attempts"),
            ("POST", "/flashcards"),
            ("GET", "/flashcards"),
            ("POST", f"/flashcards/{uuid.uuid4()}/reviews"),
            ("POST", "/study-plans"),
            ("GET", "/study-plans"),
            ("PATCH", f"/study-plans/{uuid.uuid4()}/tasks/{uuid.uuid4()}"),
            ("GET", "/progress"),
        ],
    )
    def test_all_study_content_endpoints_return_501(
        self, method: str, path_suffix: str
    ) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        app = _make_app(study_content_router, user_id=user_id, kb_id=kb_id)
        with TestClient(app) as client:
            resp = client.request(
                method, f"/api/v1/knowledge-bases/{kb_id}{path_suffix}"
            )
        assert resp.status_code == 501
        assert resp.json()["phase"] == "15"
