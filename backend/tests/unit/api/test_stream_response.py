"""Unit tests for POST /conversations/{id}/stream."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.answer import get_answer_use_case
from app.api.dependencies.scope import get_kb_scope
from app.api.routers.conversations import _FAILED_MESSAGE, _REJECTED_MESSAGE
from app.api.routers.conversations import router as conversations_router
from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.domain.errors import GenerationRejectedError, ProviderError
from app.domain.scope import ScopeContext
from app.infrastructure.database.session import get_session
from app.infrastructure.models.entailment import OllamaClaimEntailment

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


def _rejecting_use_case(tokens: list[str] | None = None) -> MagicMock:
    """A use case whose stream raises the way validation does — after any tokens it sent."""

    async def _gen():
        for t in tokens or []:
            yield t
        raise GenerationRejectedError("answer rejected after validation: REJECTED")

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


class TestRejectedAnswer:
    """A rejected answer arrives after the 200, so it has to be reported on the stream.

    Letting the error escape the generator tears the connection: the student's client
    raises a read error and cannot tell a withheld answer from a crashed server.
    """

    def test_rejection_does_not_tear_the_connection(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_rejecting_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.status_code == 200

    def test_rejection_is_sent_as_an_error_event(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_rejecting_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert "event: error\n" in resp.text

    def test_rejection_explains_why_no_answer_arrived(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_rejecting_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert "could not be verified" in resp.text

    def test_rejection_still_terminates_the_stream(self) -> None:
        """A client waiting on the sentinel would otherwise read until it timed out."""
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_rejecting_use_case())) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.text.endswith("data: [DONE]\n\n")

    def test_tokens_sent_before_the_rejection_are_kept(self) -> None:
        """Whatever already reached the student stays; the error is appended after it."""
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        with TestClient(_make_app(session, use_case=_rejecting_use_case(["A"]))) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert (
            resp.text == f"data: A\n\nevent: error\ndata: {_REJECTED_MESSAGE}\n\ndata: [DONE]\n\n"
        )

    def test_the_answer_stream_is_still_closed(self) -> None:
        """The turn is recorded in cleanup, so a rejected turn must record too."""
        closed: list[str] = []

        async def _gen() -> AsyncIterator[str]:
            try:
                raise GenerationRejectedError("rejected")
                yield ""  # pragma: no cover — unreachable, marks this a generator
            finally:
                closed.append("closed")

        use_case = MagicMock()
        use_case.execute = AsyncMock(return_value=_gen())
        session = _get_session(_conv_row(conv_id=_CONV_ID))

        with TestClient(_make_app(session, use_case=use_case)) as client:
            client.post(_STREAM_URL, json={"query": "q"})

        assert closed == ["closed"]


class TestStreamCleanup:
    """The turn is recorded in the stream's cleanup, so the endpoint has to run it."""

    def test_the_endpoint_closes_the_answer_stream(self) -> None:
        """Left to the garbage collector, the record has no guaranteed arrival time."""
        closed: list[str] = []

        async def _gen() -> AsyncIterator[str]:
            try:
                yield "answer"
            finally:
                closed.append("closed")

        use_case = MagicMock()
        use_case.execute = AsyncMock(return_value=_gen())
        session = _get_session(_conv_row(conv_id=_CONV_ID))

        with TestClient(_make_app(session, use_case=use_case)) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})

        assert resp.status_code == 200
        assert closed == ["closed"]


class TestAnswerUseCaseWiring:
    """The dependency itself, which every test above replaces with a mock.

    Overriding it is what the route tests need and also what let the constructor and its
    caller drift apart unnoticed: adding a required parameter to AnswerUseCase broke this
    function without failing a single test, because nothing here ever called it.
    """

    async def test_builds_a_use_case_with_every_required_collaborator(self) -> None:
        use_case = await get_answer_use_case(
            retrieve=MagicMock(),
            scope=_SCOPE,
            container=MagicMock(),
        )

        assert isinstance(use_case, AnswerUseCase)

    async def test_supplies_the_entailment_checker(self) -> None:
        """Validation cannot run without it, and the use case would raise on construction."""
        use_case = await get_answer_use_case(
            retrieve=MagicMock(),
            scope=_SCOPE,
            container=MagicMock(),
        )

        assert isinstance(use_case._entailment, OllamaClaimEntailment)


def _failing_use_case(exc: Exception, tokens: list[str] | None = None) -> MagicMock:
    """A use case whose stream breaks partway rather than being refused."""

    async def _gen():
        for t in tokens or []:
            yield t
        raise exc

    uc = MagicMock()
    uc.execute = AsyncMock(return_value=_gen())
    return uc


class TestFailedGeneration:
    """A generation that broke is not a generation that was refused.

    Both arrive after the 200 and neither can change the status code, so both have to be
    reported on the open stream. What must not happen is the two becoming
    indistinguishable: a failure is somebody's bug, and telling the student politely
    cannot be the thing that hides it.
    """

    def test_a_provider_failure_does_not_tear_the_connection(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(ProviderError("ollama", "connection lost", retryable=True))
        with TestClient(_make_app(session, use_case=use_case)) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.status_code == 200

    def test_a_provider_failure_is_reported_as_an_error_event(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(ProviderError("ollama", "connection lost", retryable=True))
        with TestClient(_make_app(session, use_case=use_case)) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert f"event: error\ndata: {_FAILED_MESSAGE}\n\n" in resp.text

    def test_a_failure_is_not_described_as_a_withheld_answer(self) -> None:
        """Saying an answer could not be verified would blame the student's material."""
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(RuntimeError("boom"))
        with TestClient(_make_app(session, use_case=use_case)) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert _REJECTED_MESSAGE not in resp.text

    def test_a_failure_still_terminates_the_stream(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(RuntimeError("boom"))
        with TestClient(_make_app(session, use_case=use_case)) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.text.endswith("data: [DONE]\n\n")

    def test_tokens_sent_before_the_failure_are_kept(self) -> None:
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(RuntimeError("boom"), ["partial"])
        with TestClient(_make_app(session, use_case=use_case)) as client:
            resp = client.post(_STREAM_URL, json={"query": "q"})
        assert resp.text.startswith("data: partial\n\n")

    def test_the_failure_is_logged_with_its_traceback(self) -> None:
        """Reporting it to the student must not be what stops anyone finding it."""
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(RuntimeError("boom"))
        with (
            patch("app.api.routers.conversations._log") as log,
            TestClient(_make_app(session, use_case=use_case)) as client,
        ):
            client.post(_STREAM_URL, json={"query": "q"})
        log.error.assert_called_once()
        assert log.error.call_args.kwargs["exc_info"] is True

    def test_the_answer_stream_is_still_closed(self) -> None:
        """The turn is recorded in cleanup, so a failed turn must record too."""
        closed: list[str] = []

        async def _gen() -> AsyncIterator[str]:
            try:
                raise RuntimeError("boom")
                yield ""  # pragma: no cover — unreachable, marks this a generator
            finally:
                closed.append("closed")

        use_case = MagicMock()
        use_case.execute = AsyncMock(return_value=_gen())
        session = _get_session(_conv_row(conv_id=_CONV_ID))

        with TestClient(_make_app(session, use_case=use_case)) as client:
            client.post(_STREAM_URL, json={"query": "q"})

        assert closed == ["closed"]

    def test_a_sink_that_cannot_write_does_not_break_the_stream(self) -> None:
        """Found in the wild: the log call raised and took the response down with it.

        A traceback carrying an em dash met a cp1252 console, `UnicodeEncodeError` came
        out of the logging call inside the handler, and the student got the torn
        connection the handler existed to prevent.
        """
        session = _get_session(_conv_row(conv_id=_CONV_ID))
        use_case = _failing_use_case(RuntimeError("boom"))
        with (
            patch("app.api.routers.conversations._log") as log,
            TestClient(_make_app(session, use_case=use_case)) as client,
        ):
            log.error.side_effect = UnicodeEncodeError("charmap", "\u2014", 0, 1, "unmappable")
            resp = client.post(_STREAM_URL, json={"query": "q"})

        assert resp.status_code == 200
        assert f"event: error\ndata: {_FAILED_MESSAGE}\n\n" in resp.text
        assert resp.text.endswith("data: [DONE]\n\n")
