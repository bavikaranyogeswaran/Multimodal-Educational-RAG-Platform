"""Unit tests for JWKS key caching and JWT verification.

Tests use a locally generated RSA keypair — no real Supabase connection.
The JwksClient's HTTP fetch is mocked so the cache and key-matching logic can
be exercised without network access.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from jwt.algorithms import RSAAlgorithm

from app.configuration.settings import SupabaseSettings
from app.domain.errors import AuthenticationError
from app.infrastructure.auth.jwt import extract_user_id
from app.infrastructure.auth.jwks import JwksClient

_TEST_KID = "test-key-1"
_TEST_AUDIENCE = "authenticated"


# ---------------------------------------------------------------------------
# Shared helpers
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


def _jwks_response(private_key: RSAPrivateKey, kid: str = _TEST_KID) -> dict[str, Any]:
    public_key = private_key.public_key()
    jwk_dict: dict[str, Any] = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = kid
    jwk_dict["alg"] = "RS256"
    return {"keys": [jwk_dict]}


def _mock_http(jwks_data: dict[str, Any]) -> Any:
    """Return a mock `httpx.AsyncClient` context manager that serves *jwks_data*."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=jwks_data)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    return client


def _settings(audience: str = _TEST_AUDIENCE) -> SupabaseSettings:
    return SupabaseSettings(jwt_audience=audience)


# ---------------------------------------------------------------------------
# JwksClient
# ---------------------------------------------------------------------------


class TestJwksClient:
    async def test_returns_public_key_for_known_kid(self) -> None:
        pk = _private_key()
        mock_client = _mock_http(_jwks_response(pk))

        with patch("app.infrastructure.auth.jwks.httpx.AsyncClient", return_value=mock_client):
            jwks = JwksClient(url="https://example.com/jwks.json", cache_seconds=600)
            key = await jwks.get_rsa_key(_TEST_KID)

        assert key is not None

    async def test_caches_keys_between_calls(self) -> None:
        pk = _private_key()
        mock_client = _mock_http(_jwks_response(pk))

        with patch("app.infrastructure.auth.jwks.httpx.AsyncClient", return_value=mock_client):
            jwks = JwksClient(url="https://example.com/jwks.json", cache_seconds=600)
            await jwks.get_rsa_key(_TEST_KID)
            await jwks.get_rsa_key(_TEST_KID)

        # Only one HTTP call despite two key lookups.
        assert mock_client.get.call_count == 1

    async def test_raises_for_unknown_kid(self) -> None:
        pk = _private_key()
        mock_client = _mock_http(_jwks_response(pk, kid=_TEST_KID))

        with patch("app.infrastructure.auth.jwks.httpx.AsyncClient", return_value=mock_client):
            jwks = JwksClient(url="https://example.com/jwks.json", cache_seconds=600)
            with pytest.raises(AuthenticationError, match="No signing key"):
                await jwks.get_rsa_key("unknown-kid-xyz")

    async def test_raises_on_fetch_error(self) -> None:
        import httpx

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("app.infrastructure.auth.jwks.httpx.AsyncClient", return_value=client):
            jwks = JwksClient(url="https://example.com/jwks.json", cache_seconds=600)
            with pytest.raises(AuthenticationError, match="Failed to fetch JWKS"):
                await jwks.get_rsa_key(_TEST_KID)


# ---------------------------------------------------------------------------
# Minimal JWKS client stub used by extract_user_id tests
# ---------------------------------------------------------------------------


class _StubJwksClient:
    """Returns the test public key directly, bypassing HTTP."""

    def __init__(self, private_key: RSAPrivateKey, valid_kid: str = _TEST_KID) -> None:
        self._public_key = private_key.public_key()
        self._valid_kid = valid_kid

    async def get_rsa_key(self, kid: str) -> Any:
        if kid != self._valid_kid:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return self._public_key


# ---------------------------------------------------------------------------
# extract_user_id
# ---------------------------------------------------------------------------


class TestExtractUserId:
    async def test_valid_token_returns_user_id(self) -> None:
        pk = _private_key()
        user_id = uuid.uuid4()
        token = _make_token(pk, sub=str(user_id))

        result = await extract_user_id(token, _StubJwksClient(pk), _settings())

        assert result == user_id

    async def test_expired_token_raises(self) -> None:
        pk = _private_key()
        token = _make_token(pk, exp_delta=-10)

        with pytest.raises(AuthenticationError, match="expired"):
            await extract_user_id(token, _StubJwksClient(pk), _settings())

    async def test_wrong_audience_raises(self) -> None:
        pk = _private_key()
        token = _make_token(pk, aud="wrong-audience")

        with pytest.raises(AuthenticationError, match="audience"):
            await extract_user_id(token, _StubJwksClient(pk), _settings())

    async def test_malformed_token_raises(self) -> None:
        pk = _private_key()

        with pytest.raises(AuthenticationError, match="Malformed"):
            await extract_user_id("not.a.token", _StubJwksClient(pk), _settings())

    async def test_missing_kid_in_header_raises(self) -> None:
        pk = _private_key()
        user_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "aud": _TEST_AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=3600)).timestamp()),
        }
        # Encode without a kid header.
        token = pyjwt.encode(payload, pk, algorithm="RS256")

        with pytest.raises(AuthenticationError, match="kid"):
            await extract_user_id(token, _StubJwksClient(pk), _settings())

    async def test_unknown_kid_raises(self) -> None:
        pk = _private_key()
        token = _make_token(pk, kid="some-other-kid")
        stub = _StubJwksClient(pk, valid_kid=_TEST_KID)

        with pytest.raises(AuthenticationError):
            await extract_user_id(token, stub, _settings())

    async def test_non_uuid_sub_raises(self) -> None:
        pk = _private_key()
        token = _make_token(pk, sub="not-a-uuid")

        with pytest.raises(AuthenticationError, match="UUID"):
            await extract_user_id(token, _StubJwksClient(pk), _settings())
