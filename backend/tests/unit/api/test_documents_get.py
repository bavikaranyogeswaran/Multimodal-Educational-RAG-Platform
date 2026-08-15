"""Unit tests for GET /documents/{id} and GET /documents/{id}/status endpoints.

All DB and auth dependencies are replaced via dependency_overrides.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.routers.documents import router as documents_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 1, 15, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)


# ---------------------------------------------------------------------------
# Factories and helpers
# ---------------------------------------------------------------------------


def _doc_row(
    *,
    doc_id: uuid.UUID | None = None,
    status: str = "PENDING",
    failure_reason: str | None = None,
    page_count: int | None = 10,
) -> MagicMock:
    """Minimal mock DocumentModel row that _doc_to_entity can deserialize."""
    row = MagicMock()
    row.id = doc_id or uuid.uuid4()
    row.user_id = _USER_ID
    row.knowledge_base_id = _KB_ID
    row.filename = "lecture.pdf"
    row.content_type = "application/pdf"
    row.byte_size = 204800
    row.storage_key = f"{_USER_ID}/{_KB_ID}/{row.id}/original.pdf"
    row.status = status
    row.title = None
    row.page_count = page_count
    row.checksum = "abc123"
    row.language = "en"
    row.failure_reason = failure_reason
    row.created_at = _NOW
    row.updated_at = _NOW
    row.processed_at = None
    return row


def _session_for_list(rows: list) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


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
    scope_raises_404: bool = False,
    auth_raises_401: bool = False,
) -> FastAPI:
    app = FastAPI()

    app.dependency_overrides[get_session] = _session_override(session)

    # get_kb_scope is overridden completely, so it is the single control point
    # for both auth failures and scope misses — the underlying get_current_user
    # is never called when the override is in place.
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

    app.include_router(documents_router, prefix="/api/v1")
    return app


def _get_url(doc_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/documents/{doc_id}"


def _status_url(doc_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{_KB_ID}/documents/{doc_id}/status"


# ---------------------------------------------------------------------------
# GET /{document_id}
# ---------------------------------------------------------------------------


class TestGetDocument:
    def test_returns_200_for_existing_document(self) -> None:
        doc_id = uuid.uuid4()
        session = _session_for_get(_doc_row(doc_id=doc_id))
        with TestClient(_make_app(session)) as client:
            resp = client.get(_get_url(doc_id))
        assert resp.status_code == 200

    def test_response_contains_expected_fields(self) -> None:
        doc_id = uuid.uuid4()
        session = _session_for_get(_doc_row(doc_id=doc_id, page_count=42))
        with TestClient(_make_app(session)) as client:
            body = client.get(_get_url(doc_id)).json()
        assert body["id"] == str(doc_id)
        assert body["knowledge_base_id"] == str(_KB_ID)
        assert body["filename"] == "lecture.pdf"
        assert body["content_type"] == "application/pdf"
        assert body["byte_size"] == 204800
        assert body["page_count"] == 42
        assert body["status"] == "PENDING"
        assert body["language"] == "en"

    def test_storage_key_not_in_response(self) -> None:
        doc_id = uuid.uuid4()
        session = _session_for_get(_doc_row(doc_id=doc_id))
        with TestClient(_make_app(session)) as client:
            body = client.get(_get_url(doc_id)).json()
        assert "storage_key" not in body

    def test_returns_404_when_document_not_found(self) -> None:
        session = _session_for_get(None)
        with TestClient(_make_app(session)) as client:
            resp = client.get(_get_url(uuid.uuid4()))
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Document not found"

    def test_returns_401_without_auth(self) -> None:
        session = _session_for_get(None)
        with TestClient(_make_app(session, auth_raises_401=True)) as client:
            resp = client.get(_get_url(uuid.uuid4()))
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        session = _session_for_get(None)
        with TestClient(_make_app(session, scope_raises_404=True)) as client:
            resp = client.get(_get_url(uuid.uuid4()))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /{document_id}/status
# ---------------------------------------------------------------------------


class TestGetDocumentStatus:
    def test_returns_200_for_existing_document(self) -> None:
        doc_id = uuid.uuid4()
        session = _session_for_get(_doc_row(doc_id=doc_id))
        with TestClient(_make_app(session)) as client:
            resp = client.get(_status_url(doc_id))
        assert resp.status_code == 200

    def test_response_contains_status_fields(self) -> None:
        doc_id = uuid.uuid4()
        session = _session_for_get(_doc_row(doc_id=doc_id, status="PROCESSING", page_count=7))
        with TestClient(_make_app(session)) as client:
            body = client.get(_status_url(doc_id)).json()
        assert body["id"] == str(doc_id)
        assert body["status"] == "PROCESSING"
        assert body["page_count"] == 7
        assert body["failure_reason"] is None

    def test_failed_status_includes_reason(self) -> None:
        doc_id = uuid.uuid4()
        row = _doc_row(doc_id=doc_id, status="FAILED", failure_reason="Parse error on page 3")
        session = _session_for_get(row)
        with TestClient(_make_app(session)) as client:
            body = client.get(_status_url(doc_id)).json()
        assert body["status"] == "FAILED"
        assert body["failure_reason"] == "Parse error on page 3"

    def test_response_excludes_bulk_fields(self) -> None:
        doc_id = uuid.uuid4()
        session = _session_for_get(_doc_row(doc_id=doc_id))
        with TestClient(_make_app(session)) as client:
            body = client.get(_status_url(doc_id)).json()
        for field in ("filename", "content_type", "byte_size", "checksum", "storage_key"):
            assert field not in body, f"unexpected field in status response: {field}"

    def test_returns_404_when_document_not_found(self) -> None:
        session = _session_for_get(None)
        with TestClient(_make_app(session)) as client:
            resp = client.get(_status_url(uuid.uuid4()))
        assert resp.status_code == 404

    def test_returns_401_without_auth(self) -> None:
        session = _session_for_get(None)
        with TestClient(_make_app(session, auth_raises_401=True)) as client:
            resp = client.get(_status_url(uuid.uuid4()))
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        session = _session_for_get(None)
        with TestClient(_make_app(session, scope_raises_404=True)) as client:
            resp = client.get(_status_url(uuid.uuid4()))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

_LIST_URL = f"/api/v1/knowledge-bases/{_KB_ID}/documents"


class TestListDocuments:
    def test_returns_200_with_empty_list(self) -> None:
        with TestClient(_make_app(_session_for_list([]))) as client:
            resp = client.get(_LIST_URL)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_list_of_documents(self) -> None:
        rows = [_doc_row(doc_id=uuid.uuid4()), _doc_row(doc_id=uuid.uuid4())]
        with TestClient(_make_app(_session_for_list(rows))) as client:
            body = client.get(_LIST_URL).json()
        assert len(body) == 2

    def test_response_fields(self) -> None:
        doc_id = uuid.uuid4()
        with TestClient(_make_app(_session_for_list([_doc_row(doc_id=doc_id, page_count=5)]))) as client:
            body = client.get(_LIST_URL).json()
        item = body[0]
        assert item["id"] == str(doc_id)
        assert item["knowledge_base_id"] == str(_KB_ID)
        assert item["filename"] == "lecture.pdf"
        assert item["status"] == "PENDING"
        assert item["page_count"] == 5
        assert item["language"] == "en"

    def test_storage_key_not_in_response(self) -> None:
        with TestClient(_make_app(_session_for_list([_doc_row()]))) as client:
            body = client.get(_LIST_URL).json()
        assert "storage_key" not in body[0]

    def test_returns_401_without_auth(self) -> None:
        with TestClient(_make_app(_session_for_list([]), auth_raises_401=True)) as client:
            resp = client.get(_LIST_URL)
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        with TestClient(_make_app(_session_for_list([]), scope_raises_404=True)) as client:
            resp = client.get(_LIST_URL)
        assert resp.status_code == 404
