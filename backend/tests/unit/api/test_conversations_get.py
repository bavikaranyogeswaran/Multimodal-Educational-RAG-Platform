"""Unit tests for GET /conversations, GET /conversations/{id}, GET /conversations/{id}/messages."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.scope import get_kb_scope
from app.api.routers.conversations import router as conversations_router
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_BASE_URL = f"/api/v1/knowledge-bases/{_KB_ID}/conversations"


# ---------------------------------------------------------------------------
# Mock row factories
# ---------------------------------------------------------------------------


def _conv_row(*, conv_id: uuid.UUID | None = None, title: str = "Chapter 3") -> MagicMock:
    row = MagicMock()
    row.id = conv_id or uuid.uuid4()
    row.user_id = _USER_ID
    row.knowledge_base_id = _KB_ID
    row.title = title
    row.created_at = _NOW
    row.updated_at = _NOW
    row.active_document_id = None
    row.active_page_number = None
    row.active_figure_id = None
    row.active_table_id = None
    return row


def _msg_row(
    *,
    msg_id: uuid.UUID | None = None,
    conv_id: uuid.UUID | None = None,
    role: str = "USER",
    status: str = "RECEIVED",
    content: str = "What is a neural network?",
) -> MagicMock:
    row = MagicMock()
    row.id = msg_id or uuid.uuid4()
    row.conversation_id = conv_id or uuid.uuid4()
    row.user_id = _USER_ID
    row.knowledge_base_id = _KB_ID
    row.role = role
    row.status = status
    row.content = content
    row.created_at = _NOW
    row.updated_at = _NOW
    row.rewritten_query = None
    row.model_id = None
    row.prompt_tokens = None
    row.completion_tokens = None
    row.finish_reason = None
    # Set explicitly like every other optional column: an unset attribute on a MagicMock
    # row is a truthy mock, not None, which reads as a prompt_version on a user message.
    row.prompt_version = None
    return row


# ---------------------------------------------------------------------------
# Session mock factories
# ---------------------------------------------------------------------------


def _list_session(rows: list) -> AsyncMock:
    """Session where execute returns a scalars().all() result."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _get_session(row: MagicMock | None) -> AsyncMock:
    """Session where execute returns a scalar_one_or_none() result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _get_then_list_session(conv_row: MagicMock | None, msg_rows: list) -> AsyncMock:
    """Session that handles get-conversation, list-messages, and list-citations execute calls."""
    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = conv_row
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = msg_rows
    citations_result = MagicMock()
    citations_result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[get_result, list_result, citations_result])
    return session


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _session_override(session: AsyncMock):
    async def _inner() -> AsyncIterator[AsyncMock]:
        yield session

    return _inner


def _make_app(
    session: AsyncMock,
    *,
    scope_raises_404: bool = False,
    auth_raises_401: bool = False,
) -> FastAPI:
    app = FastAPI()

    app.dependency_overrides[get_session] = _session_override(session)

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
# GET /conversations
# ---------------------------------------------------------------------------


class TestListConversations:
    def test_returns_200_with_empty_list(self) -> None:
        session = _list_session([])
        with TestClient(_make_app(session)) as client:
            resp = client.get(_BASE_URL)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_list_of_conversations(self) -> None:
        rows = [_conv_row(title="Session A"), _conv_row(title="Session B")]
        session = _list_session(rows)
        with TestClient(_make_app(session)) as client:
            body = client.get(_BASE_URL).json()
        assert len(body) == 2
        titles = {c["title"] for c in body}
        assert titles == {"Session A", "Session B"}

    def test_response_fields(self) -> None:
        conv_id = uuid.uuid4()
        session = _list_session([_conv_row(conv_id=conv_id, title="Review")])
        with TestClient(_make_app(session)) as client:
            body = client.get(_BASE_URL).json()
        item = body[0]
        assert item["id"] == str(conv_id)
        assert item["knowledge_base_id"] == str(_KB_ID)
        assert item["title"] == "Review"
        assert item["active_document_id"] is None

    def test_returns_401_without_auth(self) -> None:
        with TestClient(_make_app(_list_session([]), auth_raises_401=True)) as client:
            resp = client.get(_BASE_URL)
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        with TestClient(_make_app(_list_session([]), scope_raises_404=True)) as client:
            resp = client.get(_BASE_URL)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /conversations/{id}
# ---------------------------------------------------------------------------


class TestGetConversation:
    def test_returns_200_for_existing_conversation(self) -> None:
        conv_id = uuid.uuid4()
        session = _get_session(_conv_row(conv_id=conv_id))
        with TestClient(_make_app(session)) as client:
            resp = client.get(f"{_BASE_URL}/{conv_id}")
        assert resp.status_code == 200

    def test_response_fields(self) -> None:
        conv_id = uuid.uuid4()
        session = _get_session(_conv_row(conv_id=conv_id, title="Exam prep"))
        with TestClient(_make_app(session)) as client:
            body = client.get(f"{_BASE_URL}/{conv_id}").json()
        assert body["id"] == str(conv_id)
        assert body["knowledge_base_id"] == str(_KB_ID)
        assert body["title"] == "Exam prep"
        assert "created_at" in body
        assert "updated_at" in body

    def test_returns_404_when_not_found(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Conversation not found"

    def test_returns_401_without_auth(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session, auth_raises_401=True)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session, scope_raises_404=True)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /conversations/{id}/messages
# ---------------------------------------------------------------------------


class TestListMessages:
    def test_returns_200_with_empty_messages(self) -> None:
        conv_id = uuid.uuid4()
        session = _get_then_list_session(_conv_row(conv_id=conv_id), [])
        with TestClient(_make_app(session)) as client:
            resp = client.get(f"{_BASE_URL}/{conv_id}/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_list_of_messages(self) -> None:
        conv_id = uuid.uuid4()
        msg_id = uuid.uuid4()
        session = _get_then_list_session(
            _conv_row(conv_id=conv_id),
            [_msg_row(msg_id=msg_id, conv_id=conv_id)],
        )
        with TestClient(_make_app(session)) as client:
            body = client.get(f"{_BASE_URL}/{conv_id}/messages").json()
        assert len(body) == 1
        assert body[0]["id"] == str(msg_id)

    def test_message_response_fields(self) -> None:
        conv_id = uuid.uuid4()
        msg_id = uuid.uuid4()
        session = _get_then_list_session(
            _conv_row(conv_id=conv_id),
            [_msg_row(msg_id=msg_id, conv_id=conv_id, role="USER", status="RECEIVED",
                      content="Explain backprop")],
        )
        with TestClient(_make_app(session)) as client:
            body = client.get(f"{_BASE_URL}/{conv_id}/messages").json()
        msg = body[0]
        assert msg["id"] == str(msg_id)
        assert msg["conversation_id"] == str(conv_id)
        assert msg["role"] == "USER"
        assert msg["status"] == "RECEIVED"
        assert msg["content"] == "Explain backprop"
        assert msg["rewritten_query"] is None
        assert msg["model_id"] is None

    def test_returns_404_when_conversation_not_found(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Conversation not found"

    def test_returns_401_without_auth(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session, auth_raises_401=True)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages")
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        session = _get_session(None)
        with TestClient(_make_app(session, scope_raises_404=True)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /conversations/{id}/messages/{msg_id}/sources
# ---------------------------------------------------------------------------


def _source_row(
    *,
    chunk_id: uuid.UUID | None = None,
    rank: int = 1,
    score: float = 0.8,
    document_id: uuid.UUID | None = None,
    page_start: int = 3,
    filename: str = "lecture.pdf",
    title: str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.chunk_id = chunk_id or uuid.uuid4()
    row.rank = rank
    row.score = score
    row.document_id = document_id or uuid.uuid4()
    row.page_start = page_start
    row.filename = filename
    row.title = title
    return row


def _sources_session(chunk_rows: list, cited_ids: list) -> AsyncMock:
    """Session for the sources endpoint: first execute uses .all(), second uses .scalars().all()."""
    chunk_result = MagicMock()
    chunk_result.all.return_value = chunk_rows
    cited_result = MagicMock()
    cited_result.scalars.return_value.all.return_value = cited_ids
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[chunk_result, cited_result])
    return session


class TestListMessageSources:
    def test_returns_200_with_empty_list_when_no_chunks(self) -> None:
        session = _sources_session([], [])
        with TestClient(_make_app(session)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages/{uuid.uuid4()}/sources")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_source_with_correct_fields(self) -> None:
        chunk_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        row = _source_row(chunk_id=chunk_id, rank=1, score=0.75, document_id=doc_id, page_start=5, filename="notes.pdf", title=None)
        session = _sources_session([row], [])
        with TestClient(_make_app(session)) as client:
            body = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages/{uuid.uuid4()}/sources").json()
        assert len(body) == 1
        assert body[0]["document_name"] == "notes.pdf"
        assert body[0]["page_number"] == 5
        assert body[0]["score"] == 0.75
        assert body[0]["rank"] == 1
        assert body[0]["cited"] is False

    def test_cited_flag_true_when_chunk_in_citations(self) -> None:
        chunk_id = uuid.uuid4()
        row = _source_row(chunk_id=chunk_id)
        session = _sources_session([row], [chunk_id])
        with TestClient(_make_app(session)) as client:
            body = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages/{uuid.uuid4()}/sources").json()
        assert body[0]["cited"] is True

    def test_document_title_takes_precedence_over_filename(self) -> None:
        row = _source_row(filename="notes.pdf", title="Lecture 3 — Backprop")
        session = _sources_session([row], [])
        with TestClient(_make_app(session)) as client:
            body = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages/{uuid.uuid4()}/sources").json()
        assert body[0]["document_name"] == "Lecture 3 — Backprop"

    def test_returns_401_without_auth(self) -> None:
        with TestClient(_make_app(_sources_session([], []), auth_raises_401=True)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages/{uuid.uuid4()}/sources")
        assert resp.status_code == 401

    def test_returns_404_for_foreign_kb(self) -> None:
        with TestClient(_make_app(_sources_session([], []), scope_raises_404=True)) as client:
            resp = client.get(f"{_BASE_URL}/{uuid.uuid4()}/messages/{uuid.uuid4()}/sources")
        assert resp.status_code == 404
