"""Unit tests for POST /conversations/{id}/stream."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.answer import get_answer_use_case
from app.api.dependencies.scope import get_kb_scope
from app.api.routers.conversations import router as conversations_router
from app.application.commands.answer import AnswerCommand
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_CONV_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_BASE_URL = f"/api/v1/knowledge-bases/{_KB_ID}/conversations"
_STREAM_URL = f"{_BASE_URL}/{_CONV_ID}/stream"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _conv_row(*, conv_id: uuid.UUID | None = None) -> MagicMock:
    row = MagicMock()
    row.id = conv_id or uuid.uuid4()
    row.user_id = _USER_ID
    row.knowledge_base_id = _KB_ID
    row.title = "Lecture 1"
    row.created_at = _NOW
    row.updated_at = _NOW
    row.active_document_id = None
    row.active_page_number = None
    row.active_figure_id = None
    row.active_table_id = None
    return row


def _get_session(row: MagicMock | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _mock_use_case(tokens: list[str] | None = None) -> MagicMock:
    async def _gen():
        for t in tokens or []:
            yield t

    uc = MagicMock()
    uc.execute = AsyncMock(return_value=_gen())
    return uc


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(
    session: AsyncMock,
    *,
    use_case: MagicMock | None = None,
    scope_raises_404: bool = False,
    auth_raises_401: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_session] = _session_override(session)

    if use_case is not None:
        app.dependency_overrides[get_answer_use_case] = lambda: use_case

    if auth_raises_401:

        def _unauthed() -> ScopeContext:
            raise HTTPException(
                status_code=401,
                detail="Missing Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        app.dependency_overrides[get_kb_scope] = _unauthed
    elif scope_raises_404:

        def _missing() -> ScopeContext:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        app.dependency_overrides[get_kb_scope] = _missing
    else:
        app.dependency_overrides[get_kb_scope] = lambda: _SCOPE

    app.include_router(conversations_router, prefix="/api/v1")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStreamResponse:
    def test_returns_200_with_valid_request(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "What is momentum?"})
        assert resp.status_code == 200

    def test_content_type_is_event_stream(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert "text/event-stream" in resp.headers["content-type"]

    def test_single_token_formatted_as_sse(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case(["Hello"]))) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert "data: Hello\n\n" in resp.text

    def test_done_sentinel_appended(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case(["A"]))) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.text.endswith("data: [DONE]\n\n")

    def test_full_sse_body_for_two_tokens(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case(["A", "B"]))) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.text == "data: A\n\ndata: B\n\ndata: [DONE]\n\n"

    def test_empty_stream_yields_only_done_sentinel(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case([]))) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.text == "data: [DONE]\n\n"

    def test_use_case_called_with_correct_scope(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        uc = _mock_use_case()
        with TestClient(_make_app(session, use_case=uc)) as client:
            client.post(_STREAM_URL, json={"query": "q"})
        cmd: AnswerCommand = uc.execute.call_args.args[0]
        assert cmd.scope == _SCOPE

    def test_use_case_called_with_correct_conversation_id(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        uc = _mock_use_case()
        with TestClient(_make_app(session, use_case=uc)) as client:
            client.post(_STREAM_URL, json={"query": "q"})
        cmd: AnswerCommand = uc.execute.call_args.args[0]
        assert cmd.conversation_id == _CONV_ID

    def test_use_case_called_with_correct_query(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        uc = _mock_use_case()
        with TestClient(_make_app(session, use_case=uc)) as client:
            client.post(_STREAM_URL, json={"query": "What is momentum?"})
        cmd: AnswerCommand = uc.execute.call_args.args[0]
        assert cmd.query == "What is momentum?"

    def test_returns_404_when_conversation_not_found(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session, use_case=_mock_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Conversation not found"

    def test_returns_422_when_query_missing(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_mock_use_case())) as client:
            resp = client.post(_STREAM_URL, json={})
        assert resp.status_code == 422

    def test_returns_401_without_auth(self) -> None:
        session = _get_session(None)
        with TestClient(
            _make_app(session, use_case=_mock_use_case(), auth_raises_401=True)
        ) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        session = _get_session(None)
        with TestClient(
            _make_app(session, use_case=_mock_use_case(), scope_raises_404=True)
        ) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.status_code == 404
