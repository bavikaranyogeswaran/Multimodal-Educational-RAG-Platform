"""Security tests: authentication and KB ownership enforcement on document upload.

Exercises the full request chain (real get_current_user + real get_kb_scope) against
the document POST route. The JWKS client and DB session are stubs; no real network or
storage calls are made.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pypdf
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.container import get_container
from app.api.middleware.errors import register_exception_handlers
from app.api.routers.documents import router as documents_router
from app.configuration.settings import get_settings
from app.domain.errors import AuthenticationError
from app.infrastructure.database.session import get_session

_KID = "test-key-1"
_AUDIENCE = "authenticated"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _private_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_token(pk: RSAPrivateKey, *, sub: str, exp_delta: int = 3600) -> str:
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
    """Returns the test RSA public key for any token signed with the known kid."""

    def __init__(self, pk: RSAPrivateKey) -> None:
        self._public_key = pk.public_key()

    async def get_signing_key(self, kid: str) -> Any:
        if kid != _KID:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return self._public_key


def _session_returning(owner_id: uuid.UUID | None) -> AsyncMock:
    """Mock session whose scope check returns a row with the given user_id."""
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
    s = MagicMock()
    s.supabase.jwt_audience = _AUDIENCE
    s.storage.max_upload_bytes = 200 * 1024 * 1024
    s.storage.max_upload_pages = 1500
    return s


def _make_pdf(n_pages: int = 1) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(n_pages):
        writer.add_page(pypdf.PageObject.create_blank_page(width=612, height=792))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_app(
    pk: RSAPrivateKey,
    session: AsyncMock,
    *,
    storage: AsyncMock | None = None,
) -> FastAPI:
    """Test app with real auth + scope, stub JWKS, mock DB, and mock storage."""
    mock_storage = storage if storage is not None else AsyncMock()
    mock_container = MagicMock()
    mock_container.storage = mock_storage

    app = FastAPI()
    app.state.jwks_client = _StubJwksClient(pk)
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[get_container] = lambda: mock_container
    app.dependency_overrides[get_settings] = _mock_settings
    app.include_router(documents_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


def _upload_url(kb_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{kb_id}/documents"


# ---------------------------------------------------------------------------
# Authentication enforcement
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_upload_without_auth_returns_401() -> None:
    """Requests with no Authorization header must be rejected with 401."""
    kb_id = uuid.uuid4()
    pk = _private_key()
    session = _session_returning(uuid.uuid4())

    with TestClient(_make_app(pk, session)) as client:
        resp = client.post(
            _upload_url(kb_id),
            files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
        )

    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.security
@pytest.mark.gate
def test_upload_with_expired_token_returns_401() -> None:
    """Tokens with an elapsed exp claim must be rejected before the upload runs."""
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id), exp_delta=-3600)
    session = _session_returning(user_id)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.post(
            _upload_url(kb_id),
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
        )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# KB ownership enforcement
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_upload_to_foreign_kb_returns_404() -> None:
    """User A's valid token must not allow uploading to User B's KB."""
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
        resp = client.post(
            _upload_url(kb_id),
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
        )

    assert resp.status_code == 404


@pytest.mark.security
@pytest.mark.gate
def test_upload_to_missing_kb_returns_404() -> None:
    """Uploading to a KB that does not exist must return 404."""
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))
    session = _session_returning(None)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.post(
            _upload_url(kb_id),
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
        )

    assert resp.status_code == 404


@pytest.mark.security
@pytest.mark.gate
def test_foreign_and_missing_kb_upload_responses_are_identical() -> None:
    """A foreign KB and a missing KB must produce the same 404 response.

    An attacker who can distinguish the two cases can enumerate valid KB IDs
    without accessing their contents.
    """
    user_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))

    with patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()):
        with TestClient(_make_app(pk, _session_returning(None))) as client:
            r_missing = client.post(
                _upload_url(uuid.uuid4()),
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
            )
        with TestClient(_make_app(pk, _session_returning(uuid.uuid4()))) as client:
            r_foreign = client.post(
                _upload_url(uuid.uuid4()),
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
            )

    assert r_missing.status_code == r_foreign.status_code == 404
    assert r_missing.json() == r_foreign.json()


# ---------------------------------------------------------------------------
# Positive control
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_authenticated_user_can_upload_to_own_kb() -> None:
    """An authenticated user uploading to their own KB must receive 201.

    Ensures the test setup is not trivially broken — a passing ownership
    check must result in a successful upload, not a false-positive 404.
    """
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))
    session = _session_returning(user_id)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.post(
            _upload_url(kb_id),
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
        )

    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Storage key isolation
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_storage_key_is_scoped_to_authenticated_identity() -> None:
    """The storage key must embed the JWT-authenticated user and KB IDs.

    A forged or manipulated request body cannot direct file writes into another
    user's storage prefix because the key is derived from the verified scope,
    not from request parameters.
    """
    user_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))
    session = _session_returning(user_id)
    storage = AsyncMock()

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session, storage=storage)) as client,
    ):
        client.post(
            _upload_url(kb_id),
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("lecture.pdf", _make_pdf(), "application/pdf")},
        )

    storage.put.assert_called_once()
    key: str = storage.put.call_args.args[0]
    assert key.startswith(str(user_id) + "/"), (
        f"storage key {key!r} does not begin with the authenticated user's ID"
    )
    assert f"/{kb_id}/" in key, (
        f"storage key {key!r} does not contain the KB ID from the authenticated scope"
    )
