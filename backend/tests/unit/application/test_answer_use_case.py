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
    repo.save_message = AsyncMock()
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

    async def test_history_passed_to_retrieve_query(self) -> None:
        user_msg = _msg(MessageRole.USER, "prior question")
        asst_msg = _msg(MessageRole.ASSISTANT, "prior answer")
        # DB returns newest-first: assistant reply first, then the user question.
        repo = _mock_repo(messages=[asst_msg, user_msg])
        retrieve = _mock_retrieve()
        await _make_use_case(retrieve=retrieve, repo=repo).execute(_BASE_CMD)
        query_arg: RetrieveEvidenceQuery = retrieve.execute.call_args.args[0]
        assert len(query_arg.history) == 2
        assert query_arg.history[0].role is MessageRole.USER
        assert query_arg.history[1].role is MessageRole.ASSISTANT


# ---------------------------------------------------------------------------
# Message persistence
# ---------------------------------------------------------------------------


class TestMessagePersistence:
    async def test_user_message_saved_during_execute(self) -> None:
        repo = _mock_repo()
        await _make_use_case(repo=repo).execute(_BASE_CMD)
        # save_message for the user turn is called eagerly inside execute(), before
        # the caller even touches the returned generator.
        assert repo.save_message.await_count >= 1

    async def test_user_message_has_received_status(self) -> None:
        repo = _mock_repo()
        await _make_use_case(repo=repo).execute(_BASE_CMD)
        saved: Message = repo.save_message.call_args_list[0].args[1]
        assert saved.role is MessageRole.USER
        assert saved.status is MessageStatus.RECEIVED

    async def test_user_message_content_matches_query(self) -> None:
        repo = _mock_repo()
        await _make_use_case(repo=repo).execute(_BASE_CMD)
        saved: Message = repo.save_message.call_args_list[0].args[1]
        assert saved.content.value == _BASE_CMD.query

    async def test_user_message_saved_before_retrieval(self) -> None:
        call_order: list[str] = []

        repo = _mock_repo()
        repo.save_message = AsyncMock(
            side_effect=lambda *a, **kw: call_order.append("save_message")
        )
        retrieve = _mock_retrieve()
        retrieve.execute = AsyncMock(
            side_effect=lambda *a, **kw: call_order.append("retrieve") or []
        )

        await _make_use_case(retrieve=retrieve, repo=repo).execute(_BASE_CMD)

        assert call_order.index("save_message") < call_order.index("retrieve")

    async def test_assistant_message_saved_after_stream_consumed(self) -> None:
        tokens = ["Back", "prop", "agation"]
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo, gateway=_mock_gateway(tokens=tokens)).execute(
            _BASE_CMD
        )
        _ = [t async for t in stream]
        # Two calls: user message + assistant message.
        assert repo.save_message.await_count == 2

    async def test_assistant_message_content_is_joined_tokens(self) -> None:
        tokens = ["Back", "prop", "agation"]
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo, gateway=_mock_gateway(tokens=tokens)).execute(
            _BASE_CMD
        )
        _ = [t async for t in stream]
        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.content.value == "Backpropagation"

    async def test_assistant_message_has_completed_status(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo, gateway=_mock_gateway(tokens=["ok"])).execute(
            _BASE_CMD
        )
        _ = [t async for t in stream]
        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.role is MessageRole.ASSISTANT
        assert assistant.status is MessageStatus.COMPLETED

    async def test_failed_message_saved_on_stream_error(self) -> None:
        async def _failing():
            yield "partial"
            raise RuntimeError("model error")

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(return_value=_failing())
        repo = _mock_repo()

        stream = await _make_use_case(repo=repo, gateway=gateway).execute(_BASE_CMD)

        try:
            async for _ in stream:
                pass
        except RuntimeError:
            pass

        assert repo.save_message.await_count == 2
        failed: Message = repo.save_message.call_args_list[1].args[1]
        assert failed.role is MessageRole.ASSISTANT
        assert failed.status is MessageStatus.FAILED
