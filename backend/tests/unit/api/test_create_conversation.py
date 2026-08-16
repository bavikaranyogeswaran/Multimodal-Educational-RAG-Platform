"""Unit tests for POST /knowledge-bases/{kb_id}/conversations."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.middleware.errors import register_exception_handlers
from app.api.routers.conversations import router as conversations_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_URL = f"/api/v1/knowledge-bases/{_KB_ID}/conversations"
_VALID_BODY = {"title": "Chapter 3 study session"}


def _save_session() -> AsyncMock:
    return AsyncMock()


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(
    session: AsyncMock | None = None,
    *,
    scope_raises_404: bool = False,
    auth_raises_401: bool = False,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    s = session if session is not None else _save_session()
    app.dependency_overrides[get_session] = _session_override(s)

    if auth_raises_401:

        def _unauthed() -> ScopeContext:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        app.dependency_overrides[get_kb_scope] = _unauthed
    elif scope_raises_404:

        def _missing() -> ScopeContext:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        app.dependency_overrides[get_kb_scope] = _missing
    else:
        app.dependency_overrides[get_kb_scope] = lambda: _SCOPE

    app.include_router(conversations_router, prefix="/api/v1")
    return app


class TestCreateConversation:
    def test_returns_201_on_valid_request(self) -> None:
        with TestClient(_make_app()) as client:
            resp = client.post(_URL, json=_VALID_BODY)
        assert resp.status_code == 201

    def test_response_contains_expected_fields(self) -> None:
        with TestClient(_make_app()) as client:
            body = client.post(_URL, json=_VALID_BODY).json()
        assert "id" in body
        assert body["knowledge_base_id"] == str(_KB_ID)
        assert body["title"] == "Chapter 3 study session"
        assert "created_at" in body
        assert "updated_at" in body
        assert body["active_document_id"] is None
        assert body["active_page_number"] is None
        assert body["active_figure_id"] is None
        assert body["active_table_id"] is None

    def test_id_is_valid_uuid(self) -> None:
        with TestClient(_make_app()) as client:
            body = client.post(_URL, json=_VALID_BODY).json()
        uuid.UUID(body["id"])

    def test_active_document_context_in_response(self) -> None:
        doc_id = uuid.uuid4()
        req = {"title": "Review session", "active_document_id": str(doc_id)}
        with TestClient(_make_app()) as client:
            body = client.post(_URL, json=req).json()
        assert body["active_document_id"] == str(doc_id)

    def test_title_required(self) -> None:
        with TestClient(_make_app()) as client:
            resp = client.post(_URL, json={})
        assert resp.status_code == 422

    def test_empty_title_rejected(self) -> None:
        with TestClient(_make_app()) as client:
            resp = client.post(_URL, json={"title": ""})
        assert resp.status_code == 422

    def test_page_number_without_document_rejected(self) -> None:
        req = {"title": "Review", "active_page_number": 5}
        with TestClient(_make_app()) as client:
            resp = client.post(_URL, json=req)
        assert resp.status_code == 422

    def test_figure_and_table_mutually_exclusive(self) -> None:
        req = {
            "title": "Review",
            "active_document_id": str(uuid.uuid4()),
            "active_figure_id": str(uuid.uuid4()),
            "active_table_id": str(uuid.uuid4()),
        }
        with TestClient(_make_app()) as client:
            resp = client.post(_URL, json=req)
        assert resp.status_code == 422

    def test_returns_401_without_auth(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.post(_URL, json=_VALID_BODY)
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.post(_URL, json=_VALID_BODY)
        assert resp.status_code == 404


class TestCreateConversationIsDurable:
    """A 201 carrying an id has to mean the row exists.

    The session dependency yields a session and closes it without committing, so a
    handler that writes and returns hands the caller an identifier for a conversation
    that was rolled back on the way out.
    """

    def test_commits_the_session(self) -> None:
        session = _save_session()
        with TestClient(_make_app(session)) as client:
            resp = client.post(_URL, json=_VALID_BODY)

        assert resp.status_code == 201
        session.commit.assert_awaited_once()

    def test_commits_after_the_write(self) -> None:
        call_order: list[str] = []
        session = _save_session()
        session.merge = AsyncMock(
            side_effect=lambda *_args, **_kwargs: call_order.append("write")
        )
        session.commit = AsyncMock(
            side_effect=lambda *_args, **_kwargs: call_order.append("commit")
        )

        with TestClient(_make_app(session)) as client:
            client.post(_URL, json=_VALID_BODY)

        # Committing before the write would persist an empty transaction.
        assert call_order == ["write", "commit"]

    def test_no_commit_when_the_request_is_rejected(self) -> None:
        session = _save_session()
        with TestClient(_make_app(session)) as client:
            resp = client.post(_URL, json={"title": ""})

        assert resp.status_code == 422
        session.commit.assert_not_awaited()
