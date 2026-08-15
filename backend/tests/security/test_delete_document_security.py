"""Security tests for DELETE /knowledge-bases/{kb_id}/documents/{id}.

Verifies that the delete endpoint enforces authentication and KB ownership
before executing any mutation — an unauthenticated or cross-user caller must
receive the same generic error shape as any other protected resource.

Markers: security (selectable as a suite), gate (zero-tolerance release gate).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.routers.documents import router as documents_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_USER_A = uuid.uuid4()
_USER_B = uuid.uuid4()
_KB_ID = uuid.uuid4()
_DOC_ID = uuid.uuid4()
_DELETE_URL = f"/api/v1/knowledge-bases/{_KB_ID}/documents/{_DOC_ID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _session_for_delete(row: MagicMock | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _doc_row() -> MagicMock:
    row = MagicMock()
    row.id = _DOC_ID
    row.user_id = _USER_A
    row.knowledge_base_id = _KB_ID
    row.filename = "lecture.pdf"
    row.content_type = "application/pdf"
    row.byte_size = 204800
    row.storage_key = f"{_USER_A}/{_KB_ID}/{_DOC_ID}/original.pdf"
    row.status = "PENDING"
    row.title = None
    row.page_count = 10
    row.checksum = "abc123"
    row.language = "en"
    row.failure_reason = None
    from datetime import UTC, datetime

    now = datetime(2025, 1, 15, tzinfo=UTC)
    row.created_at = now
    row.updated_at = now
    row.processed_at = None
    return row


def _make_app(
    *,
    auth_raises_401: bool = False,
    scope_raises_404: bool = False,
    with_doc: bool = False,
) -> FastAPI:
    app = FastAPI()
    session = _session_for_delete(_doc_row() if with_doc else None)
    app.dependency_overrides[get_session] = _session_override(session)

    if auth_raises_401:

        def _unauthed() -> ScopeContext:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        app.dependency_overrides[get_kb_scope] = _unauthed
    elif scope_raises_404:

        def _foreign() -> ScopeContext:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        app.dependency_overrides[get_kb_scope] = _foreign
    else:
        app.dependency_overrides[get_kb_scope] = lambda: ScopeContext(
            user_id=_USER_A, knowledge_base_id=_KB_ID
        )

    app.include_router(documents_router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
class TestDeleteDocumentSecurity:
    def test_unauthenticated_returns_401(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert resp.status_code == 401

    def test_unauthenticated_response_includes_www_authenticate(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert "WWW-Authenticate" in resp.headers

    def test_unauthenticated_body_has_only_detail_key(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert set(resp.json().keys()) == {"detail"}

    def test_cross_user_kb_returns_404(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert resp.status_code == 404

    def test_cross_user_kb_body_has_only_detail_key(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert set(resp.json().keys()) == {"detail"}

    def test_cross_user_kb_body_does_not_contain_kb_id(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert str(_KB_ID) not in resp.text

    def test_cross_user_and_nonexistent_kb_responses_are_identical(self) -> None:
        # FR-AUTH-13: foreign KB and missing KB must return identical 404 shapes.
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp_foreign = client.delete(_DELETE_URL)
        other_url = f"/api/v1/knowledge-bases/{uuid.uuid4()}/documents/{_DOC_ID}"
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp_missing = client.delete(other_url)
        assert resp_foreign.status_code == resp_missing.status_code
        assert resp_foreign.json() == resp_missing.json()

    def test_authenticated_owner_receives_202(self) -> None:
        with TestClient(_make_app(with_doc=True)) as client:
            resp = client.delete(_DELETE_URL)
        assert resp.status_code == 202

    def test_authenticated_owner_response_status_is_deleting(self) -> None:
        with TestClient(_make_app(with_doc=True)) as client:
            body = client.delete(_DELETE_URL).json()
        assert body["status"] == "DELETING"
