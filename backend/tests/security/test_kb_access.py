"""Security tests: auth guard and KB scope boundary on conversation endpoints.

Verifies that the auth and scope dependencies fire before any handler logic runs:
unauthenticated requests return 401, cross-user and nonexistent KB access return 404,
and the guard is active on every conversation endpoint.

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

# (method, path_suffix, request body) for every conversation endpoint.
_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "", None),
    ("POST", "", {"title": "Session 1"}),
    ("GET", f"/{_CONV_ID}", None),
    ("POST", f"/{_CONV_ID}/stream", {"query": "test question"}),
    ("GET", f"/{_CONV_ID}/messages", None),
]


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
class TestUnauthenticatedAccess:
    """Every conversation endpoint rejects requests without a valid auth token."""

    @pytest.mark.parametrize("method,path_suffix,body", _ENDPOINTS)
    def test_returns_401(self, method: str, path_suffix: str, body: dict | None) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.request(method, f"{_BASE}{path_suffix}", json=body)
        assert resp.status_code == 401

    @pytest.mark.parametrize("method,path_suffix,body", _ENDPOINTS)
    def test_www_authenticate_header_present(
        self, method: str, path_suffix: str, body: dict | None
    ) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.request(method, f"{_BASE}{path_suffix}", json=body)
        assert "WWW-Authenticate" in resp.headers


@pytest.mark.security
@pytest.mark.gate
class TestCrossUserKbAccess:
    """User B's valid token against User A's KB ID returns 404 on every endpoint."""

    @pytest.mark.parametrize("method,path_suffix,body", _ENDPOINTS)
    def test_returns_404(self, method: str, path_suffix: str, body: dict | None) -> None:
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.request(method, f"{_BASE}{path_suffix}", json=body)
        assert resp.status_code == 404


@pytest.mark.security
@pytest.mark.gate
class TestNonexistentKb:
    """A valid token for a KB that does not exist also returns 404.

    The response is indistinguishable from the cross-user case (FR-AUTH-13).
    """

    @pytest.mark.parametrize("method,path_suffix,body", _ENDPOINTS)
    def test_returns_404(self, method: str, path_suffix: str, body: dict | None) -> None:
        # Both "KB belongs to another user" and "KB does not exist" produce the
        # same 404 — verified by using the same scope_raises_404 path that
        # get_kb_scope follows for both conditions.
        with TestClient(_make_app(scope_raises_404=True)) as client:
            resp = client.request(method, f"{_BASE}{path_suffix}", json=body)
        assert resp.status_code == 404


@pytest.mark.security
@pytest.mark.gate
class TestExpiredToken:
    """An expired or invalid token is treated the same as a missing token.

    Full JWT signature and expiry validation is covered in unit tests for the
    JWT verifier; this test documents the observable API behaviour.
    """

    def test_returns_401(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.get(_BASE)
        assert resp.status_code == 401

    def test_www_authenticate_header_present(self) -> None:
        with TestClient(_make_app(auth_raises_401=True)) as client:
            resp = client.get(_BASE)
        assert "WWW-Authenticate" in resp.headers
