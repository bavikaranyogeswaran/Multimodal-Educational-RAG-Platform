"""Security tests: end-to-end RLS check via the API layer.

Simulates user A's KB existing in the database (direct ownership in the mock
row), then attempts to read it as user B through the real knowledge-bases
router. Verifies that the API returns 404 and discloses no KB data in the
error body.

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

from app.api.routers.knowledge_bases import router as knowledge_bases_router
from app.domain.errors import AuthenticationError
from app.infrastructure.database.session import get_session

_KID = "test-key-1"
_AUDIENCE = "authenticated"

# Fields that must never appear in an error response for a foreign KB.
_KB_DATA_FIELDS = {
    "name",
    "description",
    "subject",
    "learning_goal",
    "preferred_language",
    "explanation_level",
    "exam_date",
    "graph_enabled",
    "active_index_version",
    "active_graph_version",
    "created_at",
    "updated_at",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _private_key() -> RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _make_token(pk: RSAPrivateKey, *, sub: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "aud": _AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "role": "authenticated",
    }
    return pyjwt.encode(payload, pk, algorithm="RS256", headers={"kid": _KID})


class _StubJwksClient:
    def __init__(self, pk: RSAPrivateKey) -> None:
        self._public_key = pk.public_key()

    async def get_rsa_key(self, kid: str) -> Any:
        if kid != _KID:
            raise AuthenticationError(f"No signing key found for kid={kid!r}")
        return self._public_key


def _session_with_owner(owner_id: uuid.UUID) -> AsyncMock:
    """Mock session that returns a row whose user_id is owner_id."""
    row = MagicMock(user_id=owner_id)
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
def test_foreign_kb_returns_404_not_kb_data() -> None:
    """User B reading user A's KB must receive a 404 with no KB fields.

    Simulates: user A's KB exists in the database (mock row owned by user_a).
    User B presents a valid token and requests the same KB ID.
    The API must return 404 and the error body must contain no KB data.
    """
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()

    user_b_token = _make_token(pk, sub=str(user_b_id))
    session = _session_with_owner(user_a_id)

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.get(
            f"/api/v1/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {user_b_token}"},
        )

    assert resp.status_code == 404

    body = resp.json()
    assert body.get("detail") == "Knowledge base not found"
    leaked = _KB_DATA_FIELDS & set(body.keys())
    assert not leaked, f"Error body leaked KB fields: {leaked}"


@pytest.mark.security
@pytest.mark.gate
def test_foreign_kb_and_missing_kb_responses_are_identical() -> None:
    """FR-AUTH-13: a foreign KB and a missing KB must be indistinguishable.

    An attacker who can distinguish the two cases can enumerate valid KB IDs,
    even without reading their contents. The status code and body must be
    identical regardless of which case actually applies.
    """
    user_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_id))

    session_foreign = _session_with_owner(uuid.uuid4())
    session_missing = AsyncMock()
    result_empty = MagicMock()
    result_empty.one_or_none.return_value = None
    session_missing.execute = AsyncMock(return_value=result_empty)

    with patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()):
        with TestClient(_make_app(pk, session_foreign)) as client:
            r_foreign = client.get(
                f"/api/v1/knowledge-bases/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {token}"},
            )
        with TestClient(_make_app(pk, session_missing)) as client:
            r_missing = client.get(
                f"/api/v1/knowledge-bases/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert r_foreign.status_code == r_missing.status_code == 404
    assert r_foreign.json() == r_missing.json()


@pytest.mark.security
@pytest.mark.gate
def test_own_kb_accessible_after_rls_check() -> None:
    """Positive control: user A CAN read their own KB when auth + scope pass.

    Ensures the test setup is not trivially broken — a passing ownership check
    must result in 200, not a false-positive 404.
    """
    user_a_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    pk = _private_key()
    token = _make_token(pk, sub=str(user_a_id))
    now = datetime.now(UTC)

    # MagicMock(name=...) sets the mock's internal label, not a .name attribute.
    # Set KB attributes explicitly to avoid this pitfall.
    kb_row = MagicMock()
    kb_row.id = kb_id
    kb_row.user_id = user_a_id
    kb_row.name = "Test KB"
    kb_row.description = None
    kb_row.subject = None
    kb_row.learning_goal = None
    kb_row.preferred_language = "en"
    kb_row.explanation_level = "INTERMEDIATE"
    kb_row.exam_date = None
    kb_row.graph_enabled = False
    kb_row.active_index_version = 1
    kb_row.active_graph_version = 1
    kb_row.created_at = now
    kb_row.updated_at = now

    # get_kb_scope calls execute().one_or_none(); repo.get() calls execute().scalar_one_or_none().
    scope_result = MagicMock()
    scope_result.one_or_none.return_value = MagicMock(user_id=user_a_id)
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = kb_row

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[scope_result, get_result])

    with (
        patch("app.api.dependencies.auth.get_settings", return_value=_mock_settings()),
        TestClient(_make_app(pk, session)) as client,
    ):
        resp = client.get(
            f"/api/v1/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(user_a_id)
    assert body["name"] == "Test KB"
