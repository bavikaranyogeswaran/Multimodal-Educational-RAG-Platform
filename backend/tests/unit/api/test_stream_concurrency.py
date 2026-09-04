"""Unit tests for concurrency control on POST /{conversation_id}/stream.

Covers: global semaphore throttle, per-user throttle, semaphore release on
completion, and semaphore release on 404 abort.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.answer import get_answer_use_case
from app.api.dependencies.scope import get_kb_scope
from app.api.middleware.errors import register_exception_handlers
from app.api.routers.conversations import router as conversations_router
from app.application.commands.answer import AnswerUseCase
from app.configuration.settings import Settings, get_settings
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_CONV_ID = uuid.uuid4()
_URL = f"/api/v1/knowledge-bases/{_KB_ID}/conversations/{_CONV_ID}/stream"
_BODY = {"query": "What is gradient descent?"}


# ---------------------------------------------------------------------------
# Fakes and helpers
# ---------------------------------------------------------------------------


def _conv_row() -> MagicMock:
    row = MagicMock()
    row.id = _CONV_ID
    row.user_id = _USER_ID
    row.knowledge_base_id = _KB_ID
    row.title = "Study session"
    row.created_at = _NOW
    row.updated_at = _NOW
    row.active_document_id = None
    row.active_page_number = None
    row.active_figure_id = None
    row.active_table_id = None
    return row


def _get_session_returning(row: MagicMock | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


async def _empty_stream() -> AsyncIterator[str]:
    return
    yield  # make it an async generator


def _use_case_returning(tokens: list[str]) -> AsyncMock:
    async def _stream(*_a: Any, **_kw: Any) -> AsyncIterator[str]:
        for t in tokens:
            yield t

    uc = AsyncMock(spec=AnswerUseCase)
    uc.execute = AsyncMock(return_value=_stream())
    return uc


def _make_app(
    *,
    global_sem: asyncio.Semaphore | None = None,
    user_sems: dict[str, asyncio.Semaphore] | None = None,
    session: AsyncMock | None = None,
    use_case: Any = None,
    max_concurrent: int = 2,
    max_per_user: int = 1,
    timeout_seconds: int = 60,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    # Semaphore state on app.state (normally set in lifespan)
    app.state.generation_semaphore = global_sem or asyncio.Semaphore(max_concurrent)
    app.state.user_generation_semaphores = user_sems if user_sems is not None else {}

    s = session or _get_session_returning(_conv_row())
    app.dependency_overrides[get_session] = _session_override(s)
    app.dependency_overrides[get_kb_scope] = lambda: _SCOPE

    if use_case is not None:
        app.dependency_overrides[get_answer_use_case] = lambda: use_case

    # Settings override: minimal, only the concurrency knobs matter
    fake_model = MagicMock()
    fake_model.max_concurrent_generations = max_concurrent
    fake_model.max_concurrent_generations_per_user = max_per_user
    fake_model.generation_timeout_seconds = timeout_seconds

    fake_settings = MagicMock(spec=Settings)
    fake_settings.model = fake_model
    app.dependency_overrides[get_settings] = lambda: fake_settings

    app.include_router(conversations_router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# Throttle: global capacity
# ---------------------------------------------------------------------------


class TestGlobalThrottle:
    def test_returns_429_when_global_semaphore_is_full(self) -> None:
        # A semaphore initialised to 0 is locked from the start — no slots available.
        full_sem = asyncio.Semaphore(0)
        app = _make_app(global_sem=full_sem, use_case=_use_case_returning([]))
        with TestClient(app) as client:
            resp = client.post(_URL, json=_BODY)
        assert resp.status_code == 429

    def test_429_body_describes_capacity(self) -> None:
        full_sem = asyncio.Semaphore(0)
        app = _make_app(global_sem=full_sem, use_case=_use_case_returning([]))
        with TestClient(app) as client:
            resp = client.post(_URL, json=_BODY)
        assert "too many" in resp.json()["detail"].lower()

    def test_global_semaphore_not_decremented_on_429(self) -> None:
        # If we return 429 the slot was never actually acquired.
        full_sem = asyncio.Semaphore(0)
        app = _make_app(global_sem=full_sem, use_case=_use_case_returning([]))
        with TestClient(app) as client:
            client.post(_URL, json=_BODY)
        # Semaphore(0) stays at 0 — not negative.
        assert full_sem._value == 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# Throttle: per-user capacity
# ---------------------------------------------------------------------------


class TestPerUserThrottle:
    def test_returns_429_when_user_semaphore_is_full(self) -> None:
        # Global has a free slot; user semaphore has none.
        user_sem = asyncio.Semaphore(0)
        user_sems = {str(_USER_ID): user_sem}
        app = _make_app(
            global_sem=asyncio.Semaphore(2),
            user_sems=user_sems,
            use_case=_use_case_returning([]),
        )
        with TestClient(app) as client:
            resp = client.post(_URL, json=_BODY)
        assert resp.status_code == 429

    def test_global_semaphore_released_when_user_throttled(self) -> None:
        # If we hold the global slot but fail the user check, we must put it back.
        global_sem = asyncio.Semaphore(1)
        user_sem = asyncio.Semaphore(0)
        app = _make_app(
            global_sem=global_sem,
            user_sems={str(_USER_ID): user_sem},
            use_case=_use_case_returning([]),
        )
        with TestClient(app) as client:
            client.post(_URL, json=_BODY)
        # Global slot returned — value back to 1.
        assert global_sem._value == 1  # noqa: SLF001


# ---------------------------------------------------------------------------
# Happy path: semaphores acquired and released
# ---------------------------------------------------------------------------


class TestSemaphoreLifecycle:
    def test_semaphores_released_after_stream_completes(self) -> None:
        global_sem = asyncio.Semaphore(1)
        app = _make_app(global_sem=global_sem, use_case=_use_case_returning(["hello"]))
        with TestClient(app) as client:
            client.post(_URL, json=_BODY)
        # Both semaphores back to full after the response is delivered.
        assert global_sem._value == 1  # noqa: SLF001

    def test_semaphores_released_after_404_abort(self) -> None:
        # The conversation lookup returns None → 404. Slots must still be released.
        global_sem = asyncio.Semaphore(1)
        session = _get_session_returning(None)  # conversation not found
        app = _make_app(
            global_sem=global_sem,
            session=session,
            use_case=_use_case_returning([]),
        )
        with TestClient(app) as client:
            resp = client.post(_URL, json=_BODY)
        assert resp.status_code == 404
        assert global_sem._value == 1  # noqa: SLF001

    def test_stream_delivers_tokens_and_done_sentinel(self) -> None:
        app = _make_app(use_case=_use_case_returning(["foo", "bar"]))
        with TestClient(app, base_url="http://test") as client:
            resp = client.post(_URL, json=_BODY)
        assert resp.status_code == 200
        assert "foo" in resp.text
        assert "bar" in resp.text
        assert "[DONE]" in resp.text
