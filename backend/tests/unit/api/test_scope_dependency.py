"""Unit tests for the get_kb_scope FastAPI dependency.

The database session and the auth dependency are both replaced via
dependency_overrides so no real database or JWT verification is needed.

FR-AUTH-13: a missing KB and a foreign KB must return the same 404 response —
the caller must not be able to distinguish the two cases.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.scope import get_kb_scope
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

# ---------------------------------------------------------------------------
# Test-app factory
# ---------------------------------------------------------------------------


def _session_override(session: AsyncMock):
    """Return an async-generator dependency that yields the given session mock."""

    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(session: AsyncMock, user_id: uuid.UUID) -> FastAPI:
    """Minimal FastAPI app with one KB-scoped endpoint."""
    test_app = FastAPI()
    test_app.dependency_overrides[get_current_user] = lambda: user_id
    test_app.dependency_overrides[get_session] = _session_override(session)

    @test_app.get("/kbs/{kb_id}")
    async def scoped_route(
        scope: Annotated[ScopeContext, Depends(get_kb_scope)],
    ) -> dict[str, str]:
        return {
            "user_id": str(scope.user_id),
            "kb_id": str(scope.knowledge_base_id),
        }

    return test_app


def _session_returning(user_id: uuid.UUID | None) -> AsyncMock:
    """Return a mock session whose execute returns a row with the given user_id."""
    row = None if user_id is None else MagicMock(user_id=user_id)
    result = MagicMock()
    result.one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetKbScope:
    def test_own_kb_returns_scope_context(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session = _session_returning(user_id)

        with TestClient(_make_app(session, user_id)) as client:
            response = client.get(f"/kbs/{kb_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == str(user_id)
        assert body["kb_id"] == str(kb_id)

    def test_missing_kb_returns_404(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session = _session_returning(None)  # no row found

        with TestClient(_make_app(session, user_id)) as client:
            response = client.get(f"/kbs/{kb_id}")

        assert response.status_code == 404

    def test_foreign_kb_returns_404(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        session = _session_returning(other_user_id)  # row exists, wrong owner

        with TestClient(_make_app(session, user_id)) as client:
            response = client.get(f"/kbs/{kb_id}")

        assert response.status_code == 404

    def test_missing_and_foreign_responses_are_identical(self) -> None:
        """FR-AUTH-13: missing KB and foreign KB must be indistinguishable."""
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()

        with TestClient(_make_app(_session_returning(None), user_id)) as c_missing:
            r_missing = c_missing.get(f"/kbs/{kb_id}")

        with TestClient(_make_app(_session_returning(uuid.uuid4()), user_id)) as c_foreign:
            r_foreign = c_foreign.get(f"/kbs/{kb_id}")

        assert r_missing.status_code == r_foreign.status_code == 404
        assert r_missing.json() == r_foreign.json()

    def test_scope_context_carries_correct_ids(self) -> None:
        user_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        session = _session_returning(user_id)

        with TestClient(_make_app(session, user_id)) as client:
            response = client.get(f"/kbs/{kb_id}")

        assert response.status_code == 200
        assert response.json() == {"user_id": str(user_id), "kb_id": str(kb_id)}

    def test_invalid_kb_id_format_returns_422(self) -> None:
        user_id = uuid.uuid4()
        session = _session_returning(user_id)

        with TestClient(_make_app(session, user_id)) as client:
            response = client.get("/kbs/not-a-uuid")

        assert response.status_code == 422
