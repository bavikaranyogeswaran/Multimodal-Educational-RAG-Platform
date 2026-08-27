"""Security tests: signed-URL lifetime and authorization on document URL issuance.

A signed URL is the only place the storage layer is reachable without going through
this API — it carries its own authorization, works for anyone holding it, and cannot
be revoked once issued. Its lifetime is therefore the whole of the boundary, and two
things have to hold for that boundary to mean anything:

  - the lifetime is bounded, and bounded by the value startup validated, not by a
    literal written at the call site that no invariant can see;
  - no URL is minted for a caller who has not proved they own the document.

The second is ordinary scope enforcement. The first is the one that rots quietly:
`StorageSettings` has always validated `signed_url_ttl_seconds` against a one-hour
cap, and the endpoint spent its whole life ignoring that setting in favour of a
hardcoded 300, so the check guarded a number nothing read.

Run with: uv run pytest -m security
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies.container import get_container
from app.api.middleware.errors import register_exception_handlers
from app.api.routers.documents import router as documents_router
from app.configuration.settings import StorageSettings, get_settings
from app.domain.errors import AuthenticationError
from app.infrastructure.database.session import get_session

_KID = "test-key-1"
_AUDIENCE = "authenticated"
_PRESIGNED_URL = "https://r2.example.com/signed?sig=abc"

#: The lower and upper bound NFR-SEC-05 puts on a signed URL's life.
_MIN_TTL_SECONDS = 60
_MAX_TTL_SECONDS = 3600

#: What these tests configure. Inside the bound, and distinct from both the bound's
#: edges and the old hardcoded 300, so a test asserting on it cannot pass by accident.
_TEST_TTL_SECONDS = 240

_CREATED_AT = datetime(2025, 1, 15, tzinfo=UTC)


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


def _doc_row(owner_id: uuid.UUID, kb_id: uuid.UUID) -> MagicMock:
    """A completed document row, filled well enough to convert to an entity.

    The repository maps every column on the way out, so a bare mock fails on the
    status enum long before the lifetime these tests are about is decided.
    """
    row = MagicMock()
    row.id = uuid.uuid4()
    row.user_id = owner_id
    row.knowledge_base_id = kb_id
    row.filename = "lecture.pdf"
    row.content_type = "application/pdf"
    row.byte_size = 204_800
    row.storage_key = f"{owner_id}/{kb_id}/{row.id}/original.pdf"
    row.status = "COMPLETED"
    row.title = None
    row.page_count = 10
    row.checksum = "abc123"
    row.language = "en"
    row.failure_reason = None
    row.created_at = _CREATED_AT
    row.updated_at = _CREATED_AT
    row.processed_at = None
    return row


def _session(*, kb_owner: uuid.UUID | None, doc: MagicMock | None) -> AsyncMock:
    """Mock session answering the scope check and then the document read.

    The scope dependency reads the Knowledge Base row through one_or_none; the handler
    then reads the document through scalar_one_or_none. Both come off the same result
    object because both go through the same mocked execute.
    """
    result = MagicMock()
    result.one_or_none.return_value = None if kb_owner is None else MagicMock(user_id=kb_owner)
    result.scalar_one_or_none.return_value = doc
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _settings_with_ttl(ttl: int) -> MagicMock:
    s = MagicMock()
    s.supabase.jwt_audience = _AUDIENCE
    s.storage.signed_url_ttl_seconds = ttl
    return s


def _make_app(
    pk: RSAPrivateKey,
    session: AsyncMock,
    storage: AsyncMock,
    *,
    ttl: int = _TEST_TTL_SECONDS,
) -> FastAPI:
    """Test app with real auth + scope, stub JWKS, mock DB, and mock storage."""
    container = MagicMock()
    container.storage = storage

    app = FastAPI()
    app.state.jwks_client = _StubJwksClient(pk)
    app.dependency_overrides[get_session] = _session_override(session)
    app.dependency_overrides[get_container] = lambda: container
    app.dependency_overrides[get_settings] = lambda: _settings_with_ttl(ttl)
    app.include_router(documents_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


def _storage() -> AsyncMock:
    s = AsyncMock()
    s.presigned_get_url = AsyncMock(return_value=_PRESIGNED_URL)
    return s


def _url_path(kb_id: uuid.UUID, doc_id: uuid.UUID) -> str:
    return f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/url"


# ---------------------------------------------------------------------------
# The lifetime is bounded, and comes from the validated setting
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_ttl_sent_to_storage_comes_from_configuration() -> None:
    """The endpoint must not mint URLs on a lifetime no invariant governs.

    Asserting the configured value reaches the storage adapter is what makes the
    startup bound load-bearing: a literal at the call site would be outside it.
    """
    owner, kb_id = uuid.uuid4(), uuid.uuid4()
    doc = _doc_row(owner, kb_id)
    storage = _storage()
    pk = _private_key()

    with TestClient(_make_app(pk, _session(kb_owner=owner, doc=doc), storage)) as client:
        resp = client.get(
            _url_path(kb_id, doc.id),
            headers={"Authorization": f"Bearer {_make_token(pk, sub=str(owner))}"},
        )

    assert resp.status_code == 200
    storage.presigned_get_url.assert_awaited_once_with(
        doc.storage_key, expires_in=_TEST_TTL_SECONDS
    )


@pytest.mark.security
@pytest.mark.gate
def test_issued_ttl_is_within_the_permitted_bound() -> None:
    """Whatever configuration is in force, the URL cannot outlive the cap."""
    owner, kb_id = uuid.uuid4(), uuid.uuid4()
    doc = _doc_row(owner, kb_id)
    storage = _storage()
    pk = _private_key()

    with TestClient(_make_app(pk, _session(kb_owner=owner, doc=doc), storage)) as client:
        client.get(
            _url_path(kb_id, doc.id),
            headers={"Authorization": f"Bearer {_make_token(pk, sub=str(owner))}"},
        )

    issued = storage.presigned_get_url.await_args.kwargs["expires_in"]
    assert _MIN_TTL_SECONDS <= issued <= _MAX_TTL_SECONDS


@pytest.mark.security
@pytest.mark.gate
def test_reported_expiry_matches_the_ttl_actually_requested() -> None:
    """A response promising longer than the URL lives would strand the viewer.

    The client schedules its refresh off `expires_at`. If that ran past the real
    expiry the viewer would hold a dead URL and the PDF would fail to load with no
    indication why, so the two must agree.
    """
    owner, kb_id = uuid.uuid4(), uuid.uuid4()
    doc = _doc_row(owner, kb_id)
    storage = _storage()
    pk = _private_key()

    before = datetime.now(UTC)
    with TestClient(_make_app(pk, _session(kb_owner=owner, doc=doc), storage)) as client:
        resp = client.get(
            _url_path(kb_id, doc.id),
            headers={"Authorization": f"Bearer {_make_token(pk, sub=str(owner))}"},
        )
    after = datetime.now(UTC)

    reported = datetime.fromisoformat(resp.json()["expires_at"])
    requested = storage.presigned_get_url.await_args.kwargs["expires_in"]

    # The handler reads the clock once between these two samples.
    assert before + timedelta(seconds=requested) <= reported <= after + timedelta(
        seconds=requested
    )


@pytest.mark.security
@pytest.mark.gate
def test_configuration_outside_the_bound_is_refused_at_startup() -> None:
    """The bound is enforced where it can still be acted on, not logged in passing."""
    for ttl in (_MIN_TTL_SECONDS - 1, _MAX_TTL_SECONDS + 1, 0, 86_400):
        with pytest.raises(ValidationError):
            StorageSettings(signed_url_ttl_seconds=ttl)


@pytest.mark.security
def test_shipped_default_is_within_the_bound() -> None:
    """The value this deployment actually runs on, not just the ones it would reject."""
    ttl = get_settings().storage.signed_url_ttl_seconds
    assert _MIN_TTL_SECONDS <= ttl <= _MAX_TTL_SECONDS


# ---------------------------------------------------------------------------
# No URL is minted for a caller who has not proved ownership
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
def test_unauthenticated_request_is_refused_and_mints_nothing() -> None:
    """401 is necessary but not sufficient — the URL must never be generated at all."""
    kb_id, doc_id = uuid.uuid4(), uuid.uuid4()
    storage = _storage()

    with TestClient(
        _make_app(_private_key(), _session(kb_owner=uuid.uuid4(), doc=None), storage)
    ) as client:
        resp = client.get(_url_path(kb_id, doc_id))

    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
    storage.presigned_get_url.assert_not_awaited()


@pytest.mark.security
@pytest.mark.gate
def test_foreign_knowledge_base_is_refused_and_mints_nothing() -> None:
    """A signed URL generated then discarded is still a signed URL that was generated."""
    owner, attacker, kb_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    doc = _doc_row(owner, kb_id)
    storage = _storage()
    pk = _private_key()

    with TestClient(_make_app(pk, _session(kb_owner=owner, doc=doc), storage)) as client:
        resp = client.get(
            _url_path(kb_id, doc.id),
            headers={"Authorization": f"Bearer {_make_token(pk, sub=str(attacker))}"},
        )

    assert resp.status_code == 404
    storage.presigned_get_url.assert_not_awaited()


@pytest.mark.security
@pytest.mark.gate
def test_document_outside_the_scope_is_refused_and_mints_nothing() -> None:
    """The document read is scope-filtered, so a foreign id reads as absent."""
    owner, kb_id = uuid.uuid4(), uuid.uuid4()
    storage = _storage()
    pk = _private_key()

    with TestClient(
        _make_app(pk, _session(kb_owner=owner, doc=None), storage)
    ) as client:
        resp = client.get(
            _url_path(kb_id, uuid.uuid4()),
            headers={"Authorization": f"Bearer {_make_token(pk, sub=str(owner))}"},
        )

    assert resp.status_code == 404
    storage.presigned_get_url.assert_not_awaited()


@pytest.mark.security
@pytest.mark.gate
def test_expired_token_is_refused_and_mints_nothing() -> None:
    """A session that has lapsed cannot renew its reach into storage."""
    owner, kb_id = uuid.uuid4(), uuid.uuid4()
    doc = _doc_row(owner, kb_id)
    storage = _storage()
    pk = _private_key()
    expired = _make_token(pk, sub=str(owner), exp_delta=-3600)

    with TestClient(_make_app(pk, _session(kb_owner=owner, doc=doc), storage)) as client:
        resp = client.get(
            _url_path(kb_id, doc.id), headers={"Authorization": f"Bearer {expired}"}
        )

    assert resp.status_code == 401
    storage.presigned_get_url.assert_not_awaited()
