"""Security tests: authentication and KB access control.

Tests the full request chain — real get_current_user + real get_kb_scope —
against the live knowledge-bases router. The JWKS client and the database
session are both replaced with stubs so no network calls are made.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user  # noqa: F401 — used as override key
from app.api.routers.knowledge_bases import router as knowledge_bases_router
from app.domain.errors import AuthenticationError
from app.infrastructure.database.session import get_session

_KID = "test-key-1"
_AUDIENCE = "authenticated"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _private_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_token(
    pk: RSAPrivateKey,
    *,
    sub: str | None = None,
    exp_delta: int = 3600,
) -> str:
    sub = sub or str(uuid.uuid4())
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "aud": _AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_delta)).timestamp()),
        "role": "authenticated",
    }
    return pyjwt.encode(payload, pk, algorithm="RS256", headers={"kid": _KID})


class _StubJwksClient:
    """Returns the test RSA public key for any token with the known kid."""

    def __init__(self, pk: RSAPrivateKey) -> None:
        self._public_key = pk.public_key()

    async def get_rsa_key(self, kid: str) -> Any:
        if kid != _KID:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return self._public_key


def _session_returning(owner_id: uuid.UUID | None) -> AsyncMock:
    """Mock session whose execute() returns a row with the given user_id."""
    row = None if owner_id is None else MagicMock(user_id=owner_id)
    result = MagicMock()
    result.one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.supabase.jwt_audience = _AUDIENCE
    return settings


def _make_app(pk: RSAPrivateKey, session: AsyncMock) -> FastAPI:
    """Test app with real auth + scope dependencies, stub JWKS, and mock DB."""
    test_app = FastAPI()
    test_app.state.jwks_client = _StubJwksClient(pk)
    test_app.dependency_overrides[get_session] = _session_override(session)
    test_app.include_router(knowledge_bases_router, prefix="/api/v1")
    return test_app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_cross_user_kb_access_returns_404() -> None:
    """User A's valid token must not grant access to a KB owned by user B."""
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_a_id))
    session = _session_returning(user_b_id)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.get(
            f"/api/v1/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 404


@pytest.mark.security
@pytest.mark.gate
def test_unauthenticated_access_returns_401() -> None:
    """Requests without an Authorization header must be rejected with 401."""
    pk = _private_key()
    session = _session_returning(uuid.uuid4())

    with TestClient(_make_app(pk, session)) as client:
        resp = client.get(f"/api/v1/knowledge-bases/{uuid.uuid4()}")

    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.security
@pytest.mark.gate
def test_expired_token_returns_401() -> None:
    """Tokens with an elapsed exp claim must be rejected with 401."""
    user_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id), exp_delta=-60)
    session = _session_returning(user_id)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.get(
            f"/api/v1/knowledge-bases/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 401


@pytest.mark.security
@pytest.mark.gate
def test_valid_token_missing_kb_returns_404() -> None:
    """A valid token for a KB that does not exist must return 404."""
    user_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))
    session = _session_returning(None)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.get(
            f"/api/v1/knowledge-bases/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 404


@pytest.mark.security
@pytest.mark.gate
def test_missing_and_foreign_kb_responses_are_identical() -> None:
    """A missing KB and a foreign KB must produce the same 404 response (FR-AUTH-13).

    Callers must not be able to determine whether a KB ID exists by comparing
    the error bodies.
    """
    user_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))

    with patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()):
        with TestClient(_make_app(pk, _session_returning(None))) as client:
            r_missing = client.get(
                f"/api/v1/knowledge-bases/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {token}"},
            )
        with TestClient(_make_app(pk, _session_returning(uuid.uuid4()))) as client:
            r_foreign = client.get(
                f"/api/v1/knowledge-bases/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert r_missing.status_code == r_foreign.status_code == 404
    assert r_missing.json() == r_foreign.json()
