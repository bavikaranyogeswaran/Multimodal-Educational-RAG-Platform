"""Unit tests for GET /documents/{id}/url endpoint."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.container import get_container
from app.api.dependencies.scope import get_kb_scope
from app.api.routers.documents import router as documents_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 1, 15, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_PRESIGNED_URL = "https://cdn.example.com/docs/file.pdf?sig=abc"


def _doc_row(*, doc_id: uuid.UUID | None = None) -> MagicMock:
    row = MagicMock()
    row.id = doc_id or uuid.uuid4()
    row.user_id = _USER_ID
    row.knowledge_base_id = _KB_ID
    row.filename = "lecture.pdf"
    row.content_type = "application/pdf"
    row.byte_size = 204800
    row.storage_key = f"{_USER_ID}/{_KB_ID}/{row.id}/original.pdf"
    row.status = "COMPLETED"
    row.title = None
    row.page_count = 10
    row.checksum = "abc123"
    row.language = "en"
    row.failure_reason = None
    row.created_at = _NOW
    row.updated_at = _NOW
    row.processed_at = None
    return row


def _session_for_get(row: MagicMock | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(
    session: AsyncMock,
    *,
    presigned_url: str = _PRESIGNED_URL,
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

    mock_storage = AsyncMock()
    mock_storage.presigned_get_url = AsyncMock(return_value=presigned_url)
    mock_container = MagicMock()
    mock_container.storage = mock_storage
    app.dependency_overrides[get_container] = lambda: mock_container

    app.include_router(documents_router, prefix="/api/v1")
    return app


def _url_path(doc_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/documents/{doc_id}/url"


# ---------------------------------------------------------------------------
# GET /{document_id}/url — happy path
# ---------------------------------------------------------------------------


def test_url_returns_presigned_url_and_expiry() -> None:
    row = _doc_row()
    app = _make_app(_session_for_get(row))
    resp = TestClient(app).get(_url_path(row.id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == _PRESIGNED_URL
    assert "expires_at" in data


def test_url_calls_storage_with_document_storage_key() -> None:
    row = _doc_row()
    session = _session_for_get(row)
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)

    mock_storage = AsyncMock()
    mock_storage.presigned_get_url = AsyncMock(return_value=_PRESIGNED_URL)
    mock_container = MagicMock()
    mock_container.storage = mock_storage

    app = FastAPI()
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[get_kb_scope] = lambda: _SCOPE
    app.dependency_overrides[get_container] = lambda: mock_container
    app.include_router(documents_router, prefix="/api/v1")

    TestClient(app).get(_url_path(row.id))
    mock_storage.presigned_get_url.assert_awaited_once_with(
        row.storage_key, expires_in=300
    )


# ---------------------------------------------------------------------------
# GET /{document_id}/url — error paths (security)
# ---------------------------------------------------------------------------


def test_url_returns_404_when_document_not_found() -> None:
    # Document does not exist in this KB — repo returns None, endpoint returns 404.
    app = _make_app(_session_for_get(None))
    resp = TestClient(app).get(_url_path(uuid.uuid4()))
    assert resp.status_code == 404


def test_url_returns_404_when_kb_does_not_belong_to_user() -> None:
    # The scope dependency raises 404 when the KB is not owned by the requesting user.
    # A foreign-KB document therefore never reaches the storage call.
    row = _doc_row()
    app = _make_app(_session_for_get(row), scope_raises_404=True)
    resp = TestClient(app).get(_url_path(row.id))
    assert resp.status_code == 404
