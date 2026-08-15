"""Unit tests for AnswerUseCase."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.application.queries.retrieve_evidence import RetrieveEvidenceQuery
from app.domain.conversations.entities import Message
from app.domain.enums import MessageRole, MessageStatus, ModelTask
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_USER_ID = uuid.uuid4()
_KB_ID = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER_ID, knowledge_base_id=_KB_ID)
_CONV_ID = uuid.uuid4()

_BASE_CMD = AnswerCommand(
    scope=_SCOPE,
    conversation_id=_CONV_ID,
    query="What is backpropagation?",
)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ev(text: str) -> MagicMock:
    ev = MagicMock()
    ev.chunk.text = UntrustedText(text)
    return ev


def _msg(role: MessageRole, text: str) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=_CONV_ID,
        user_id=_USER_ID,
        knowledge_base_id=_KB_ID,
        role=role,
        status=MessageStatus.COMPLETED if role is MessageRole.ASSISTANT else MessageStatus.RECEIVED,
        content=UntrustedText(text),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _mock_retrieve(evidence: list | None = None) -> AsyncMock:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(return_value=evidence or [])
    return retrieve


def _mock_repo(messages: list | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.list_messages = AsyncMock(return_value=messages or [])
    return repo


def _mock_gateway(tokens: list[str] | None = None) -> MagicMock:
    async def _gen():
        for t in tokens or []:
            yield t

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(return_value=_gen())
    return gateway


def _make_use_case(
    retrieve: AsyncMock | None = None,
    repo: AsyncMock | None = None,
    gateway: MagicMock | None = None,
) -> AnswerUseCase:
    return AnswerUseCase(
        retrieve=retrieve or _mock_retrieve(),
        conversation_repo=repo or _mock_repo(),
        model_gateway=gateway or _mock_gateway(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnswerUseCase:
    async def test_retrieve_called_with_correct_query(self) -> None:
        retrieve = _mock_retrieve()
        await _make_use_case(retrieve=retrieve).execute(_BASE_CMD)
        query_arg: RetrieveEvidenceQuery = retrieve.execute.call_args.args[0]
        assert query_arg.query == _BASE_CMD.query

    async def test_retrieve_called_with_correct_scope(self) -> None:
        retrieve = _mock_retrieve()
        await _make_use_case(retrieve=retrieve).execute(_BASE_CMD)
        query_arg: RetrieveEvidenceQuery = retrieve.execute.call_args.args[0]
        assert query_arg.scope == _SCOPE

    async def test_retrieve_uses_default_top_k(self) -> None:
        retrieve = _mock_retrieve()
        await _make_use_case(retrieve=retrieve).execute(_BASE_CMD)
        query_arg: RetrieveEvidenceQuery = retrieve.execute.call_args.args[0]
        assert query_arg.top_k == 8

    async def test_custom_top_k_forwarded(self) -> None:
        retrieve = _mock_retrieve()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q", top_k=15)
        await _make_use_case(retrieve=retrieve).execute(cmd)
        query_arg: RetrieveEvidenceQuery = retrieve.execute.call_args.args[0]
        assert query_arg.top_k == 15

    async def test_history_loaded_with_conversation_id(self) -> None:
        repo = _mock_repo()
        await _make_use_case(repo=repo).execute(_BASE_CMD)
        assert repo.list_messages.call_args.args[1] == _CONV_ID

    async def test_history_loaded_with_max_history_limit(self) -> None:
        repo = _mock_repo()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q", max_history=5)
        await _make_use_case(repo=repo).execute(cmd)
        assert repo.list_messages.call_args.kwargs["limit"] == 5

    async def test_evidence_chunk_texts_in_request(self) -> None:
        gateway = _mock_gateway()
        retrieve = _mock_retrieve([_ev("Passage A"), _ev("Passage B")])
        await _make_use_case(retrieve=retrieve, gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert len(request.evidence) == 2
        assert request.evidence[0].value == "Passage A"
        assert request.evidence[1].value == "Passage B"

    async def test_empty_evidence_yields_empty_tuple(self) -> None:
        gateway = _mock_gateway()
        await _make_use_case(retrieve=_mock_retrieve([]), gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.evidence == ()

    async def test_history_reversed_to_chronological_order(self) -> None:
        user_msg = _msg(MessageRole.USER, "What is it?")
        asst_msg = _msg(MessageRole.ASSISTANT, "It is a technique...")
        # DB returns newest-first: assistant reply first, then the user question.
        repo = _mock_repo(messages=[asst_msg, user_msg])
        gateway = _mock_gateway()
        await _make_use_case(repo=repo, gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert len(request.conversation_history) == 2
        assert request.conversation_history[0].role is MessageRole.USER
        assert request.conversation_history[1].role is MessageRole.ASSISTANT

    async def test_model_task_is_answer_generation(self) -> None:
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.model_task is ModelTask.ANSWER_GENERATION

    async def test_query_in_model_request(self) -> None:
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.query == "What is backpropagation?"

    async def test_returns_stream_from_gateway(self) -> None:
        tokens = ["The", " answer", " is"]
        gateway = _mock_gateway(tokens=tokens)
        stream = await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        collected = [t async for t in stream]
        assert collected == tokens
