"""Tests for the get_current_user FastAPI dependency.

A minimal app is constructed for each test class. The JWKS client is replaced
with a stub so no network calls are made.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from unittest.mock import MagicMock, patch

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.domain.errors import AuthenticationError

_TEST_KID = "test-key-1"
_TEST_AUDIENCE = "authenticated"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _private_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_token(
    private_key: RSAPrivateKey,
    *,
    sub: str | None = None,
    aud: str = _TEST_AUDIENCE,
    kid: str = _TEST_KID,
    exp_delta: int = 3600,
) -> str:
    sub = sub or str(uuid.uuid4())
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "aud": aud,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_delta)).timestamp()),
        "role": "authenticated",
    }
    return pyjwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


class _StubJwksClient:
    def __init__(self, private_key: RSAPrivateKey, valid_kid: str = _TEST_KID) -> None:
        self._public_key = private_key.public_key()
        self._valid_kid = valid_kid

    async def get_signing_key(self, kid: str) -> Any:
        if kid != self._valid_kid:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return self._public_key


def _make_app(stub: _StubJwksClient) -> FastAPI:
    """Minimal FastAPI app with one protected endpoint."""
    test_app = FastAPI()
    test_app.state.jwks_client = stub

    @test_app.get("/protected")
    async def protected(user_id: Annotated[uuid.UUID, Depends(get_current_user)]) -> dict[str, str]:
        return {"user_id": str(user_id)}

    return test_app


def _mock_settings(audience: str = _TEST_AUDIENCE) -> MagicMock:
    settings = MagicMock()
    settings.supabase.jwt_audience = audience
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    def test_valid_token_returns_200(self) -> None:
        pk = _private_key()
        user_id = uuid.uuid4()
        token = _make_token(pk, sub=str(user_id))
        app = _make_app(_StubJwksClient(pk))

        with (
            patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
            TestClient(app) as client,
        ):
            response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        assert response.json()["user_id"] == str(user_id)

    def test_missing_header_returns_401(self) -> None:
        pk = _private_key()
        app = _make_app(_StubJwksClient(pk))

        with (
            patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
            TestClient(app) as client,
        ):
            response = client.get("/protected")

        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers

    def test_expired_token_returns_401(self) -> None:
        pk = _private_key()
        token = _make_token(pk, exp_delta=-3600)
        app = _make_app(_StubJwksClient(pk))

        with (
            patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
            TestClient(app) as client,
        ):
            response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_wrong_audience_returns_401(self) -> None:
        pk = _private_key()
        token = _make_token(pk, aud="wrong-audience")
        app = _make_app(_StubJwksClient(pk))

        with (
            patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
            TestClient(app) as client,
        ):
            response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_malformed_token_returns_401(self) -> None:
        pk = _private_key()
        app = _make_app(_StubJwksClient(pk))

        with (
            patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
            TestClient(app) as client,
        ):
            response = client.get("/protected", headers={"Authorization": "Bearer not.a.token"})

        assert response.status_code == 401

    def test_unknown_signing_key_returns_401(self) -> None:
        pk = _private_key()
        token = _make_token(pk, kid="unknown-kid")
        app = _make_app(_StubJwksClient(pk, valid_kid=_TEST_KID))

        with (
            patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
            TestClient(app) as client,
        ):
            response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 401
