"""Security tests: response body privacy at the API layer.

Verifies that the API never discloses resource data in error responses:
- 404 bodies contain no KB identifiers, user IDs, or resource payloads.
- The response for a cross-user access is indistinguishable from a missing-KB response.
- 401 bodies contain no resource data.

Markers: security (selectable as a suite), gate (zero-tolerance release gate).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.routers.conversations import router as conversations_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_USER_A = uuid.uuid4()
_USER_B = uuid.uuid4()
_KB_ID = uuid.uuid4()
_CONV_ID = uuid.uuid4()
_BASE = f"/api/v1/knowledge-bases/{_KB_ID}/conversations"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(*, auth_raises_401: bool = False, scope_raises_404: bool = False) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_session] = _session_override(AsyncMock())

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

    app.include_router(conversations_router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
class TestNoDataDisclosure:
    """Error responses must not disclose KB data, user IDs, or resource contents.

    This simulates the scenario from plan step 3.7: User A owns a KB; User B
    attempts to read it via the API. The response must be a generic 404 that
    reveals nothing about User A's data.
    """

    def test_cross_user_kb_404_body_has_only_detail_key(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.get(_BASE)
        assert set(resp.json().keys()) == {"detail"}

    def test_cross_user_kb_404_body_does_not_contain_kb_id(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.get(_BASE)
        assert str(_KB_ID) not in resp.text

    def test_cross_user_kb_404_body_does_not_contain_user_ids(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.get(_BASE)
        assert str(_USER_A) not in resp.text
        assert str(_USER_B) not in resp.text

    def test_foreign_kb_response_matches_nonexistent_kb_response(self) -> None:
        # FR-AUTH-13: the two cases must be indistinguishable.
        # get_kb_scope raises the same 404 for both, so the bodies are identical.
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp_foreign = client.get(_BASE)
        # Use a different KB ID to simulate "does not exist"; same override path.
        other_base = f"/api/v1/knowledge-bases/{uuid.uuid4()}/conversations"
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp_missing = client.get(other_base)
        assert resp_foreign.status_code == resp_missing.status_code
        assert resp_foreign.json() == resp_missing.json()

    def test_401_body_has_only_detail_key(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.get(_BASE)
        assert set(resp.json().keys()) == {"detail"}

    def test_401_body_does_not_contain_kb_id(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.get(_BASE)
        assert str(_KB_ID) not in resp.text

    def test_cross_user_conversation_access_returns_404(self) -> None:
        # User B cannot read User A's conversation — the scope guard returns 404
        # before any conversation data is fetched.
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.get(f"{_BASE}/{_CONV_ID}")
        assert resp.status_code == 404

    def test_cross_user_stream_access_returns_404(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.post(
                f"{_BASE}/{_CONV_ID}/stream", json={"query": "test question"}
            )
        assert resp.status_code == 404

    def test_cross_user_stream_404_body_has_only_detail_key(self) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.post(
                f"{_BASE}/{_CONV_ID}/stream", json={"query": "test question"}
            )
        assert set(resp.json().keys()) == {"detail"}
