"""Unit tests for AnswerUseCase."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.commands import answer as answer_module
from app.application.commands.answer import (
    _INSTRUCTIONS,
    _SAFETY_RULES,
    PROMPT_VERSION,
    AnswerCommand,
    AnswerUseCase,
    _derive_prompt_version,
)
from app.application.queries.retrieve_evidence import RetrieveEvidenceQuery
from app.domain.conversations.entities import Message
from app.domain.documents.chunks import Chunk
from app.domain.enums import (
    AnswerFidelity,
    ChunkType,
    ClaimStatus,
    InstructionCategory,
    MessageRole,
    MessageStatus,
    ModelTask,
    RequirementLevel,
    RetrieverKind,
)
from app.domain.errors import GenerationRejectedError
from app.domain.models.context_builder import ContextBuilder
from app.domain.models.entities import GenerationUsage
from app.domain.models.validation import EntailmentResult
from app.domain.ports.repositories import ConversationUnitOfWork
from app.domain.retrieval.entities import Evidence, EvidenceLabel
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

# Default gateway response: insufficient_evidence=true avoids citation and entailment
# checks, so tests that do not care about validation can use this without setting up
# evidence or mocking the entailment port in detail.
_VALID_ANSWER_JSON = json.dumps({
    "answer": "Test answer.",
    "claims": [],
    "insufficient_evidence": True,
})


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _ev(text: str, *, label: str = "[S1]") -> Evidence:
    """A real Evidence rather than a mock.

    It was a MagicMock until citations were resolved from the evidence set: resolution
    looks the cited label up in a dict keyed by EvidenceLabel, and a mock attribute never
    matches a real one, so every citation silently resolved to nothing. The label has to
    behave like a label for the test to mean anything.
    """
    return Evidence(
        label=EvidenceLabel.parse(label),
        chunk=Chunk(
            id=uuid.uuid4(),
            user_id=_USER_ID,
            knowledge_base_id=_KB_ID,
            document_id=uuid.uuid4(),
            chunk_type=ChunkType.TEXT,
            text=UntrustedText(text),
            token_count=max(1, len(text) // 4),
            ordinal=0,
            page_start=1,
            page_end=1,
            index_version=1,
            created_at=_NOW,
        ),
        retrievers=frozenset({RetrieverKind.DENSE}),
    )


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


def _mock_retrieve(evidence: list[Evidence] | None = None) -> AsyncMock:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(return_value=evidence or [])
    return retrieve


def _mock_repo(messages: list[Message] | None = None) -> AsyncMock:
    repo = AsyncMock()
    # The answer path reads list_history, not list_messages: an AsyncMock would
    # auto-create the former and hand back an empty history without saying so.
    repo.list_history = AsyncMock(return_value=messages or [])
    repo.list_messages = AsyncMock(return_value=messages or [])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    return repo


def _uow_over(repo: AsyncMock, opened: list[str] | None = None) -> ConversationUnitOfWork:
    """A unit of work that hands out the same repository every time.

    Tests assert against one repository across both transactions, so the blocks share
    an instance. `opened`, when supplied, records an entry per block so a test can see
    how many transactions the use case actually opened.
    """

    @asynccontextmanager
    async def _uow() -> AsyncIterator[AsyncMock]:
        if opened is not None:
            opened.append("open")
        yield repo

    return _uow


def _recording_retrieve(call_order: list[str]) -> Callable[..., list[Evidence]]:
    """Note that retrieval ran, then return no evidence."""

    def _record(*_args: object, **_kwargs: object) -> list[Evidence]:
        call_order.append("retrieve")
        return []

    return _record


class _FakeTokenStream:
    """A stream that reports usage the way a real provider adapter does.

    Usage appears only once the stream is drained, because that is when a provider knows
    it. A test that set it up front could not tell a correct implementation from one that
    reads the value too early.
    """

    def __init__(self, chunk: str, usage: GenerationUsage | None) -> None:
        self._chunk = chunk
        self._reported = usage
        self.usage: GenerationUsage | None = None

    async def __aiter__(self) -> AsyncIterator[str]:
        yield self._chunk
        self.usage = self._reported


def _mock_gateway(
    response: str | None = None, usage: GenerationUsage | None = None
) -> MagicMock:
    """Return a gateway whose generate_stream yields a single JSON chunk.

    The default is a valid insufficient_evidence answer so tests that do not care
    about validation pass without needing real evidence or an entailment mock.
    Passing a custom string lets tests exercise specific validation paths.

    With no `usage`, the stream reports none — which is what a bare async generator does
    and therefore what most of these tests exercise.
    """
    chunk = response if response is not None else _VALID_ANSWER_JSON

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(
        side_effect=lambda _req: _FakeTokenStream(chunk, usage)
    )
    return gateway


def _mock_entailment(status: ClaimStatus = ClaimStatus.ENTAILED) -> MagicMock:
    """Return an entailment port that always gives the same status for every passage."""
    entailment = MagicMock()

    async def _check(claim: object, passages: list[object]) -> tuple[EntailmentResult, ...]:
        return tuple(
            EntailmentResult(
                claim=claim,  # type: ignore[arg-type]
                passage_label=p.label,  # type: ignore[union-attr]
                status=status,
            )
            for p in passages
        )

    entailment.check_claim = AsyncMock(side_effect=_check)
    return entailment


def _mock_faithfulness(fidelity: AnswerFidelity = AnswerFidelity.FAITHFUL) -> MagicMock:
    """A faithfulness port that always returns the same verdict."""
    port = MagicMock()
    port.check_answer = AsyncMock(return_value=fidelity)
    return port


def _context_builder() -> ContextBuilder:
    """A real builder, generous enough that nothing under test ever gets shed.

    What the builder does with a tight budget is its own module's concern; here the
    interest is only in what AnswerUseCase hands it and does with what it returns.
    """
    return ContextBuilder(lambda text: len(text.split()), token_budget=100_000)


def _make_use_case(
    *,
    retrieve: AsyncMock | None = None,
    repo: AsyncMock | None = None,
    gateway: MagicMock | None = None,
    opened: list[str] | None = None,
    context_builder: ContextBuilder | None = None,
    entailment: MagicMock | None = None,
    faithfulness: MagicMock | None = None,
) -> AnswerUseCase:
    return AnswerUseCase(
        retrieve=retrieve or _mock_retrieve(),
        conversation_uow=_uow_over(repo or _mock_repo(), opened),
        model_gateway=gateway or _mock_gateway(),
        context_builder=context_builder or _context_builder(),
        entailment=entailment or _mock_entailment(),
        faithfulness=faithfulness or _mock_faithfulness(),
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

    async def test_the_caller_does_not_say_how_much_evidence_to_send(self) -> None:
        """It used to pass a count, and one count is wrong for one of any two questions:
        it dilutes a direct answer and starves a comparison. How many passages are worth
        sending follows from the class the query is given, and is decided downstream."""
        retrieve = _mock_retrieve()
        await _make_use_case(retrieve=retrieve).execute(_BASE_CMD)
        query_arg: RetrieveEvidenceQuery = retrieve.execute.call_args.args[0]
        assert not hasattr(query_arg, "top_k")

    async def test_history_loaded_with_conversation_id(self) -> None:
        repo = _mock_repo()
        await _make_use_case(repo=repo).execute(_BASE_CMD)
        assert repo.list_history.call_args.args[1] == _CONV_ID

    async def test_history_loaded_with_max_history_limit(self) -> None:
        repo = _mock_repo()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q", max_history=5)
        await _make_use_case(repo=repo).execute(cmd)
        assert repo.list_history.call_args.kwargs["limit"] == 5

    async def test_history_comes_from_list_history_not_list_messages(self) -> None:
        """The two differ on turns that failed or were abandoned. Reading the wrong one
        replays a placeholder to the model as something the assistant previously said."""
        repo = _mock_repo()
        await _make_use_case(repo=repo).execute(_BASE_CMD)

        assert repo.list_history.await_count == 1
        assert repo.list_messages.await_count == 0

    async def test_evidence_chunk_texts_in_request(self) -> None:
        gateway = _mock_gateway()
        retrieve = _mock_retrieve([_ev("Passage A"), _ev("Passage B")])
        await _make_use_case(retrieve=retrieve, gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert len(request.evidence) == 2
        assert request.evidence[0].text.value == "Passage A"
        assert request.evidence[1].text.value == "Passage B"

    async def test_evidence_carries_the_label_the_model_must_cite_it_by(self) -> None:
        """Without this the model has no way to say which passage supports a claim, and
        nothing downstream has a citation to check."""
        gateway = _mock_gateway()
        retrieve = _mock_retrieve([_ev("Passage A", label="[S1]"), _ev("Passage B", label="[S2]")])
        await _make_use_case(retrieve=retrieve, gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.evidence[0].label == "[S1]"
        assert request.evidence[1].label == "[S2]"

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

    async def test_the_turn_arrives_as_named_requirements(self) -> None:
        """The instructions this use case declares reach the prompt as a numbered list, so
        an answer can be checked against them one requirement at a time."""
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        names = [r.identifier for r in request.mandatory_requirements]
        assert names == [f"R{n}" for n in range(1, len(names) + 1)]
        assert len(names) > 1

    async def test_the_security_requirement_is_read_before_everything_else(self) -> None:
        """A rule stated after a style note reads as one opinion among several, because
        whatever is read last is read freshest."""
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        categories = [r.instruction.category for r in request.mandatory_requirements]
        assert categories[0] is InstructionCategory.SECURITY_AND_PRIVACY
        assert categories == sorted(categories)

    async def test_grounding_binds_critically_and_style_does_not(self) -> None:
        """The classification is what lets the budget give up a preference without giving
        up a rule alongside it."""
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        by_category = {
            r.instruction.category: r.instruction.level for r in request.mandatory_requirements
        }
        assert by_category[InstructionCategory.GROUNDING_AND_SOURCE_USE] is (
            RequirementLevel.CRITICAL
        )
        assert by_category[InstructionCategory.STYLE_PREFERENCE] is RequirementLevel.PREFERRED

    async def test_model_task_is_answer_generation(self) -> None:
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.model_task is ModelTask.ANSWER_GENERATION

    async def test_output_schema_is_populated(self) -> None:
        """The model must be told what shape to respond in before any claim can be validated."""
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.output_schema is not None
        assert len(request.output_schema) > 0

    async def test_query_in_model_request(self) -> None:
        gateway = _mock_gateway()
        await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        request = gateway.generate_stream.call_args.args[0]
        assert request.query == "What is backpropagation?"

    async def test_returns_validated_answer_text(self) -> None:
        """The caller receives the prose answer, not the raw JSON the model produced."""
        stream = await _make_use_case().execute(_BASE_CMD)
        collected = [t async for t in stream]
        assert collected == ["Test answer."]

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
            side_effect=lambda *_args, **_kwargs: call_order.append("save_message")
        )
        retrieve = _mock_retrieve()
        retrieve.execute = AsyncMock(
            side_effect=_recording_retrieve(call_order),
        )

        await _make_use_case(retrieve=retrieve, repo=repo).execute(_BASE_CMD)

        assert call_order.index("save_message") < call_order.index("retrieve")

    async def test_assistant_message_saved_after_stream_consumed(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        _ = [t async for t in stream]
        # Two calls: user message + assistant message.
        assert repo.save_message.await_count == 2

    async def test_assistant_message_content_is_validated_answer_text(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        _ = [t async for t in stream]
        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.content.value == "Test answer."

    async def test_assistant_message_has_completed_status(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        _ = [t async for t in stream]
        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.role is MessageRole.ASSISTANT
        assert assistant.status is MessageStatus.COMPLETED

    async def test_failed_message_saved_on_stream_error(self) -> None:
        async def _failing() -> AsyncIterator[str]:
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


# ---------------------------------------------------------------------------
# Transaction boundaries
# ---------------------------------------------------------------------------


class TestTransactionBoundaries:
    async def test_question_is_committed_before_the_stream_begins(self) -> None:
        opened: list[str] = []
        repo = _mock_repo()
        await _make_use_case(repo=repo, opened=opened).execute(_BASE_CMD)

        # One block, opened and closed, holding the question — durable before a single
        # token has been generated.
        assert len(opened) == 1
        assert repo.save_message.await_count == 1

    async def test_answer_is_written_in_a_second_transaction(self) -> None:
        opened: list[str] = []
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo, opened=opened).execute(_BASE_CMD)
        _ = [t async for t in stream]

        # The first block closed while the handler was still running; this one opens
        # after the response has been streamed, which is why it cannot be the same one.
        assert len(opened) == 2

    async def test_second_transaction_opens_even_when_generation_fails(self) -> None:
        async def _failing() -> AsyncIterator[str]:
            yield "partial"
            raise RuntimeError("model error")

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(return_value=_failing())
        opened: list[str] = []

        stream = await _make_use_case(gateway=gateway, opened=opened).execute(_BASE_CMD)
        try:
            async for _ in stream:
                pass
        except RuntimeError:
            pass

        assert len(opened) == 2

    async def test_no_second_transaction_if_the_stream_is_never_consumed(self) -> None:
        opened: list[str] = []
        await _make_use_case(opened=opened).execute(_BASE_CMD)

        # Nothing was generated, so there is no answer to store and no reason to open
        # a transaction to store it in.
        assert len(opened) == 1


# ---------------------------------------------------------------------------
# Evidence record — what the model was actually given
# ---------------------------------------------------------------------------


class TestRetrievalChunkPersistence:
    async def test_not_written_until_the_stream_is_consumed(self) -> None:
        repo = _mock_repo()
        retrieve = _mock_retrieve([_ev("Passage A")])
        await _make_use_case(retrieve=retrieve, repo=repo).execute(_BASE_CMD)
        # execute() returns a generator; nothing has been generated yet, so there is
        # no answer for the evidence record to hang off.
        repo.save_retrieval_chunks.assert_not_awaited()

    async def test_written_once_after_the_stream_is_consumed(self) -> None:
        repo = _mock_repo()
        retrieve = _mock_retrieve([_ev("Passage A")])
        stream = await _make_use_case(retrieve=retrieve, repo=repo).execute(_BASE_CMD)
        _ = [t async for t in stream]

        assert repo.save_retrieval_chunks.await_count == 1

    async def test_recorded_against_the_assistant_message(self) -> None:
        repo = _mock_repo()
        retrieve = _mock_retrieve([_ev("Passage A")])
        stream = await _make_use_case(retrieve=retrieve, repo=repo).execute(_BASE_CMD)
        _ = [t async for t in stream]

        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert repo.save_retrieval_chunks.call_args.args[1] == assistant.id

    async def test_carries_every_evidence_item_that_reached_the_prompt(self) -> None:
        evidence = [_ev("Passage A"), _ev("Passage B"), _ev("Passage C")]
        repo = _mock_repo()
        stream = await _make_use_case(
            retrieve=_mock_retrieve(evidence), repo=repo
        ).execute(_BASE_CMD)
        _ = [t async for t in stream]

        recorded = list(repo.save_retrieval_chunks.call_args.args[2])
        assert len(recorded) == len(evidence)
        assert recorded == evidence

    async def test_written_with_the_calls_scope(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(
            retrieve=_mock_retrieve([_ev("Passage A")]),
            repo=repo,
        ).execute(_BASE_CMD)
        _ = [t async for t in stream]

        assert repo.save_retrieval_chunks.call_args.args[0] == _SCOPE

    async def test_written_after_the_assistant_message(self) -> None:
        call_order: list[str] = []
        repo = _mock_repo()
        repo.save_message = AsyncMock(
            side_effect=lambda *_args, **_kwargs: call_order.append("message")
        )
        repo.save_retrieval_chunks = AsyncMock(
            side_effect=lambda *_args, **_kwargs: call_order.append("evidence")
        )
        stream = await _make_use_case(
            retrieve=_mock_retrieve([_ev("Passage A")]),
            repo=repo,
        ).execute(_BASE_CMD)
        _ = [t async for t in stream]

        # The record carries a foreign key to the message, so the message is written first.
        assert call_order == ["message", "message", "evidence"]

    async def test_still_written_when_generation_fails(self) -> None:
        async def _failing() -> AsyncIterator[str]:
            yield "partial"
            raise RuntimeError("model error")

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(return_value=_failing())
        evidence = [_ev("Passage A")]
        repo = _mock_repo()

        stream = await _make_use_case(
            retrieve=_mock_retrieve(evidence), repo=repo, gateway=gateway
        ).execute(_BASE_CMD)
        try:
            async for _ in stream:
                pass
        except RuntimeError:
            pass

        assert repo.save_retrieval_chunks.await_count == 1
        assert list(repo.save_retrieval_chunks.call_args.args[2]) == evidence

    async def test_empty_evidence_still_reaches_the_repository(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(
            retrieve=_mock_retrieve([]), repo=repo
        ).execute(_BASE_CMD)
        _ = [t async for t in stream]

        # Whether an empty set is worth a write is the repository's call, not this
        # use case's — keeping the decision in one place keeps the two from diverging.
        assert repo.save_retrieval_chunks.await_count == 1
        assert list(repo.save_retrieval_chunks.call_args.args[2]) == []


# ---------------------------------------------------------------------------
# Validation pipeline
# ---------------------------------------------------------------------------


class TestValidationPipeline:
    async def test_valid_answer_yields_prose_text(self) -> None:
        response = json.dumps({
            "answer": "Backprop computes gradients.",
            "claims": [{"text": "Backprop computes gradients.", "citations": ["[S1]"]}],
            "insufficient_evidence": False,
        })
        gateway = _mock_gateway(response=response)
        retrieve = _mock_retrieve([_ev("A passage about gradients.", label="[S1]")])
        entailment = _mock_entailment(ClaimStatus.ENTAILED)

        stream = await _make_use_case(
            retrieve=retrieve, gateway=gateway, entailment=entailment
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]
        assert collected == ["Backprop computes gradients."]

    async def test_insufficient_evidence_answer_is_returnable(self) -> None:
        stream = await _make_use_case().execute(_BASE_CMD)
        collected = [t async for t in stream]
        assert collected == ["Test answer."]

    async def test_parse_error_raises_generation_rejected_error(self) -> None:
        gateway = _mock_gateway(response="not valid json {{{")
        stream = await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass

    async def test_rejected_answer_raises_generation_rejected_error(self) -> None:
        response = json.dumps({
            "answer": "A contradicted claim.",
            "claims": [{"text": "A contradicted claim.", "citations": ["[S1]"]}],
            "insufficient_evidence": False,
        })
        gateway = _mock_gateway(response=response)
        retrieve = _mock_retrieve([_ev("Evidence.", label="[S1]")])
        entailment = _mock_entailment(ClaimStatus.CONTRADICTED)

        stream = await _make_use_case(
            retrieve=retrieve, gateway=gateway, entailment=entailment
        ).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass

    async def test_repairable_answer_triggers_second_generate_call(self) -> None:
        repairable = json.dumps({
            "answer": "A not-supported claim.",
            "claims": [{"text": "A not-supported claim.", "citations": ["[S1]"]}],
            "insufficient_evidence": False,
        })
        repaired = json.dumps({
            "answer": "Repaired answer.",
            "claims": [],
            "insufficient_evidence": True,
        })

        call_count = 0

        async def _alternating() -> AsyncIterator[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield repairable
            else:
                yield repaired

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=lambda _req: _alternating())
        retrieve = _mock_retrieve([_ev("Evidence.", label="[S1]")])
        entailment = _mock_entailment(ClaimStatus.NOT_SUPPORTED)

        stream = await _make_use_case(
            retrieve=retrieve, gateway=gateway, entailment=entailment
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]

        assert gateway.generate_stream.call_count == 2
        assert collected == ["Repaired answer."]

    async def test_repair_failure_raises_generation_rejected_error(self) -> None:
        bad_response = json.dumps({
            "answer": "A contradicted claim.",
            "claims": [{"text": "A contradicted claim.", "citations": ["[S1]"]}],
            "insufficient_evidence": False,
        })

        async def _always_bad() -> AsyncIterator[str]:
            yield bad_response

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=lambda _req: _always_bad())
        retrieve = _mock_retrieve([_ev("Evidence.", label="[S1]")])
        entailment_call = 0

        async def _escalating_entailment(
            claim: object, passages: list[object]
        ) -> tuple[EntailmentResult, ...]:
            nonlocal entailment_call
            entailment_call += 1
            # First call: NOT_SUPPORTED → REPAIRABLE; second call: CONTRADICTED → REJECTED
            status = (
                ClaimStatus.NOT_SUPPORTED if entailment_call == 1 else ClaimStatus.CONTRADICTED
            )
            return tuple(
                EntailmentResult(claim=claim, passage_label=p.label, status=status)  # type: ignore[arg-type, union-attr]
                for p in passages
            )

        entailment = MagicMock()
        entailment.check_claim = AsyncMock(side_effect=_escalating_entailment)

        stream = await _make_use_case(
            retrieve=retrieve, gateway=gateway, entailment=entailment
        ).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass

    async def test_entailment_only_checks_real_citations(self) -> None:
        response = json.dumps({
            "answer": "A claim with a fabricated label.",
            "claims": [
                {
                    "text": "A claim with a fabricated label.",
                    "citations": ["[S1]", "[FAKE]"],
                }
            ],
            "insufficient_evidence": False,
        })
        gateway = _mock_gateway(response=response)
        retrieve = _mock_retrieve([_ev("Evidence.", label="[S1]")])
        entailment = _mock_entailment(ClaimStatus.ENTAILED)

        stream = await _make_use_case(
            retrieve=retrieve, gateway=gateway, entailment=entailment
        ).execute(_BASE_CMD)
        # [FAKE] is fabricated but [S1] is real — claim is still REPAIRABLE (has fabricated
        # labels), so validation should not treat it as VALID. But the entailment check
        # only runs against [S1].
        try:
            async for _ in stream:
                pass
        except GenerationRejectedError:
            pass  # REPAIRABLE may become REJECTED after repair attempt with no evidence

        # entailment was called — but only with the real passage [S1], not [FAKE]
        assert entailment.check_claim.await_count >= 1
        call_args = entailment.check_claim.call_args_list[0]
        passages_arg = call_args.args[1]
        assert all(p.label == "[S1]" for p in passages_arg)

    async def test_rejected_answer_still_saves_failed_message(self) -> None:
        gateway = _mock_gateway(response="not json")
        repo = _mock_repo()

        stream = await _make_use_case(repo=repo, gateway=gateway).execute(_BASE_CMD)
        try:
            async for _ in stream:
                pass
        except GenerationRejectedError:
            pass

        assert repo.save_message.await_count == 2
        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.status is MessageStatus.FAILED


class TestCitationPersistence:
    """The record of which passage carried which claim, written once the answer is given."""

    @staticmethod
    def _cited_answer(label: str = "[S1]") -> str:
        return json.dumps({
            "answer": "Gradients flow backwards.",
            "claims": [{"text": "Gradients flow backwards.", "citations": [label]}],
            "insufficient_evidence": False,
        })

    async def test_citations_are_saved_against_the_assistant_message(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(
            retrieve=_mock_retrieve([_ev("Gradients flow backwards.", label="[S1]")]),
            repo=repo,
            gateway=_mock_gateway(response=self._cited_answer()),
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert repo.save_citations.await_count == 1
        assert repo.save_citations.call_args.args[1] == assistant.id

    async def test_one_citation_per_cited_label(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(
            retrieve=_mock_retrieve([_ev("Gradients flow backwards.", label="[S1]")]),
            repo=repo,
            gateway=_mock_gateway(response=self._cited_answer()),
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        saved = list(repo.save_citations.call_args.args[2])
        assert len(saved) == 1
        assert saved[0].label.bracketed == "[S1]"

    async def test_an_abstaining_answer_records_no_citations(self) -> None:
        """`insufficient_evidence` returns an answer with no claims, so nothing was cited
        and the citation record is empty rather than absent."""
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assert list(repo.save_citations.call_args.args[2]) == []

    async def test_a_rejected_answer_records_no_citations(self) -> None:
        """Nothing survived validation, so nothing may be recorded as a source — the
        record must not imply an answer was grounded when it was refused."""
        repo = _mock_repo()
        stream = await _make_use_case(
            repo=repo, gateway=_mock_gateway(response="not json")
        ).execute(_BASE_CMD)
        try:
            async for _ in stream:
                pass
        except GenerationRejectedError:
            pass

        assert repo.save_citations.await_count == 1
        assert list(repo.save_citations.call_args.args[2]) == []

    async def test_citations_are_written_under_the_calling_scope(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(
            retrieve=_mock_retrieve([_ev("Gradients flow backwards.", label="[S1]")]),
            repo=repo,
            gateway=_mock_gateway(response=self._cited_answer()),
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assert repo.save_citations.call_args.args[0] == _SCOPE


class TestModelMetadata:
    """What the turn cost, taken from the stream once the provider has finished."""

    @staticmethod
    def _usage() -> GenerationUsage:
        return GenerationUsage(
            model_id="gemma3:4b",
            prompt_tokens=812,
            completion_tokens=95,
            finish_reason="stop",
        )

    @staticmethod
    async def _assistant_after(repo: AsyncMock, use_case: AnswerUseCase) -> Message:
        stream = await use_case.execute(_BASE_CMD)
        async for _ in stream:
            pass
        result: Message = repo.save_message.call_args_list[1].args[1]
        return result

    async def test_records_the_model_that_answered(self) -> None:
        repo = _mock_repo()
        assistant = await self._assistant_after(
            repo,
            _make_use_case(repo=repo, gateway=_mock_gateway(usage=self._usage())),
        )

        assert assistant.model_id == "gemma3:4b"

    async def test_records_the_token_counts(self) -> None:
        repo = _mock_repo()
        assistant = await self._assistant_after(
            repo,
            _make_use_case(repo=repo, gateway=_mock_gateway(usage=self._usage())),
        )

        assert assistant.prompt_tokens == 812
        assert assistant.completion_tokens == 95

    async def test_records_the_finish_reason(self) -> None:
        repo = _mock_repo()
        assistant = await self._assistant_after(
            repo,
            _make_use_case(repo=repo, gateway=_mock_gateway(usage=self._usage())),
        )

        assert assistant.finish_reason == "stop"

    async def test_a_provider_that_reports_nothing_leaves_metadata_null(self) -> None:
        """Null, not zero. A call whose cost went unreported is not a call that cost
        nothing, and a stored zero would be indistinguishable from one that did."""
        repo = _mock_repo()
        assistant = await self._assistant_after(
            repo, _make_use_case(repo=repo, gateway=_mock_gateway())
        )

        assert assistant.model_id is None
        assert assistant.prompt_tokens is None
        assert assistant.completion_tokens is None
        assert assistant.finish_reason is None

    async def test_a_rejected_answer_still_records_what_it_cost(self) -> None:
        """The stream was drained before validation refused the result, so the tokens
        were spent. A turn that produced nothing usable is exactly the one worth being
        able to see the cost of."""
        repo = _mock_repo()
        use_case = _make_use_case(
            repo=repo, gateway=_mock_gateway(response="not json", usage=self._usage())
        )

        stream = await use_case.execute(_BASE_CMD)
        try:
            async for _ in stream:
                pass
        except GenerationRejectedError:
            pass

        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.status is MessageStatus.FAILED
        assert assistant.model_id == "gemma3:4b"
        assert assistant.prompt_tokens == 812

    async def test_a_repaired_answer_records_the_repair_call_not_the_first(self) -> None:
        """The discarded attempt is not what produced the answer that was returned."""
        repairable = json.dumps({
            "answer": "A not-supported claim.",
            "claims": [{"text": "A not-supported claim.", "citations": ["[S1]"]}],
            "insufficient_evidence": False,
        })
        repaired = json.dumps({
            "answer": "Repaired answer.",
            "claims": [],
            "insufficient_evidence": True,
        })
        calls = 0

        def _stream(_req: object) -> _FakeTokenStream:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _FakeTokenStream(
                    repairable,
                    GenerationUsage(model_id="first", prompt_tokens=1, completion_tokens=1),
                )
            return _FakeTokenStream(
                repaired,
                GenerationUsage(model_id="second", prompt_tokens=2, completion_tokens=2),
            )

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=_stream)
        repo = _mock_repo()

        assistant = await self._assistant_after(
            repo,
            _make_use_case(
                retrieve=_mock_retrieve([_ev("Evidence.", label="[S1]")]),
                repo=repo,
                gateway=gateway,
                entailment=_mock_entailment(ClaimStatus.NOT_SUPPORTED),
            ),
        )

        assert assistant.model_id == "second"
        assert assistant.prompt_tokens == 2


class TestPromptVersion:
    """Naming the template that produced an answer, so two prompts stay distinguishable."""

    async def test_is_recorded_on_the_assistant_message(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.prompt_version == PROMPT_VERSION

    async def test_is_not_recorded_on_the_question(self) -> None:
        """A question is not produced by a prompt."""
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        async for _ in stream:
            pass

        user: Message = repo.save_message.call_args_list[0].args[1]
        assert user.prompt_version is None

    async def test_is_recorded_even_when_the_answer_was_refused(self) -> None:
        """The prompt was still the one sent, and a refused answer is worth attributing
        to the template that produced it."""
        repo = _mock_repo()
        stream = await _make_use_case(
            repo=repo, gateway=_mock_gateway(response="not json")
        ).execute(_BASE_CMD)
        try:
            async for _ in stream:
                pass
        except GenerationRejectedError:
            pass

        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.status is MessageStatus.FAILED
        assert assistant.prompt_version == PROMPT_VERSION

    def test_is_derived_from_the_prompt_rather_than_hand_written(self) -> None:
        """A version someone has to remember to bump is one that eventually lies. Changing
        any part of the template must change the version without anyone editing it."""
        original = _derive_prompt_version()

        with patch.object(answer_module, "_TASK_INSTRUCTIONS", "Something else entirely."):
            changed = _derive_prompt_version()

        assert changed != original

    def test_an_instruction_change_changes_the_version(self) -> None:
        original = _derive_prompt_version()
        edited = (
            *_INSTRUCTIONS[:-1],
            replace(_INSTRUCTIONS[-1], text="Answer in a completely different register."),
        )

        with patch.object(answer_module, "_INSTRUCTIONS", edited):
            changed = _derive_prompt_version()

        assert changed != original

    def test_reordering_the_parts_changes_the_version(self) -> None:
        """The separator cannot occur in the text, so two different splits cannot collide."""
        original = _derive_prompt_version()

        with patch.object(answer_module, "_SAFETY_RULES", tuple(reversed(_SAFETY_RULES))):
            changed = _derive_prompt_version()

        assert changed != original

    def test_is_stable_across_calls(self) -> None:
        assert _derive_prompt_version() == _derive_prompt_version()

    def test_names_the_prompt_it_versions(self) -> None:
        assert PROMPT_VERSION.startswith("answer-")


class TestAbandonedTurn:
    """The student stops listening — by closing the iterator, or by the server cancelling
    the response task on disconnect. Neither raises `Exception`, so both once slipped past
    the failure handler and were recorded as completed answers."""

    @staticmethod
    def _assistant(repo: AsyncMock) -> Message:
        result: Message = repo.save_message.call_args_list[1].args[1]
        return result

    async def test_closing_the_stream_records_the_turn_as_cancelled(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)

        agen = stream.__aiter__()
        await agen.asend(None)
        await agen.aclose()

        assert self._assistant(repo).status is MessageStatus.CANCELLED

    async def test_the_answer_that_was_produced_is_still_kept(self) -> None:
        """Cancelled describes delivery, not the text. What was generated is still what
        the record should hold."""
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)

        agen = stream.__aiter__()
        await agen.asend(None)
        await agen.aclose()

        assert self._assistant(repo).content.value == "Test answer."

    async def test_cancelling_during_generation_records_cancelled(self) -> None:
        """The task is cancelled before any answer exists — the case that used to store
        the placeholder text under a COMPLETED status."""

        class _HangingStream:
            usage = None

            async def __aiter__(self) -> AsyncIterator[str]:
                await asyncio.sleep(30)
                yield "never"

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=lambda _req: _HangingStream())
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo, gateway=gateway).execute(_BASE_CMD)

        async def _consume() -> None:
            async for _ in stream:
                pass

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)

        assistant = self._assistant(repo)
        assert assistant.status is MessageStatus.CANCELLED
        assert "(generation failed)" not in assistant.content.value

    async def test_the_turn_is_still_recorded_when_abandoned(self) -> None:
        """The evidence reached the model and the question was asked; walking away does
        not undo either."""
        repo = _mock_repo()
        stream = await _make_use_case(
            repo=repo, retrieve=_mock_retrieve([_ev("Passage A")])
        ).execute(_BASE_CMD)

        agen = stream.__aiter__()
        await agen.asend(None)
        await agen.aclose()

        assert repo.save_message.await_count == 2
        assert repo.save_retrieval_chunks.await_count == 1
        assert repo.save_citations.await_count == 1

    async def test_a_refused_answer_is_still_failed_not_cancelled(self) -> None:
        """Only abandonment maps to CANCELLED. A validation refusal is a different fact
        and must not be reclassified as the student leaving."""
        repo = _mock_repo()
        stream = await _make_use_case(
            repo=repo, gateway=_mock_gateway(response="not json")
        ).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass

        assert self._assistant(repo).status is MessageStatus.FAILED

    async def test_a_completed_turn_is_unaffected(self) -> None:
        repo = _mock_repo()
        stream = await _make_use_case(repo=repo).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assert self._assistant(repo).status is MessageStatus.COMPLETED


class TestFaithfulnessInThePipeline:
    """The prose the student reads, checked against the claims already verified."""

    _CITED = json.dumps({
        "answer": "Gradients flow backwards, and training converges in nine epochs.",
        "claims": [{"text": "Gradients flow backwards.", "citations": ["[S1]"]}],
        "insufficient_evidence": False,
    })
    _REPAIRED = json.dumps({
        "answer": "Gradients flow backwards.",
        "claims": [{"text": "Gradients flow backwards.", "citations": ["[S1]"]}],
        "insufficient_evidence": False,
    })

    def _evidence(self) -> list[Evidence]:
        return [_ev("Gradients flow backwards.", label="[S1]")]

    async def test_an_overstated_answer_is_repaired_not_returned_as_it_stands(self) -> None:
        """Every claim is entailed, so nothing else in the pipeline objects. Only the
        faithfulness check sees that the prose added an epoch count from nowhere."""
        calls = 0

        def _stream(_req: object) -> _FakeTokenStream:
            nonlocal calls
            calls += 1
            return _FakeTokenStream(self._CITED if calls == 1 else self._REPAIRED, None)

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=_stream)
        fidelities = [AnswerFidelity.OVERSTATED, AnswerFidelity.FAITHFUL]
        faithfulness = MagicMock()
        faithfulness.check_answer = AsyncMock(side_effect=fidelities)

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            faithfulness=faithfulness,
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]

        assert gateway.generate_stream.call_count == 2
        assert collected == ["Gradients flow backwards."]

    async def test_a_persistently_overstated_answer_is_trimmed_to_its_claims(self) -> None:
        """It used to be refused outright. Salvage is a better answer to overstatement
        than refusal is: the prose is what overstated, the claims behind it are sound, and
        rebuilding the prose from those claims removes the overreach rather than the
        whole answer. The epoch count was never a claim, so it does not survive."""
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._CITED, None)
        )

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            faithfulness=_mock_faithfulness(AnswerFidelity.OVERSTATED),
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]

        assert collected == ["Gradients flow backwards."]
        assert "nine epochs" not in collected[0]

    async def test_a_faithful_answer_passes_through(self) -> None:
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._REPAIRED, None)
        )

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()), gateway=gateway
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]

        assert collected == ["Gradients flow backwards."]

    async def test_the_repair_instructions_mention_the_overstatement(self) -> None:
        calls = 0

        def _stream(_req: object) -> _FakeTokenStream:
            nonlocal calls
            calls += 1
            return _FakeTokenStream(self._CITED if calls == 1 else self._REPAIRED, None)

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=_stream)
        faithfulness = MagicMock()
        faithfulness.check_answer = AsyncMock(
            side_effect=[AnswerFidelity.OVERSTATED, AnswerFidelity.FAITHFUL]
        )

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            faithfulness=faithfulness,
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        repair_request = gateway.generate_stream.call_args_list[1].args[0]
        checklist = " ".join(repair_request.critical_checklist)
        assert "none of your claims covers" in checklist

    async def test_a_doomed_answer_does_not_pay_for_a_faithfulness_call(self) -> None:
        """The check is another model call, and an answer already headed for rejection
        cannot be saved by it."""
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._CITED, None)
        )
        faithfulness = _mock_faithfulness()

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            entailment=_mock_entailment(ClaimStatus.CONTRADICTED),
            faithfulness=faithfulness,
        ).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass

        faithfulness.check_answer.assert_not_called()

    async def test_an_abstaining_answer_is_not_checked_for_faithfulness(self) -> None:
        """No claims were made, so there is nothing the prose could overstate."""
        faithfulness = _mock_faithfulness()

        stream = await _make_use_case(faithfulness=faithfulness).execute(_BASE_CMD)
        async for _ in stream:
            pass

        faithfulness.check_answer.assert_not_called()


class TestNumericFidelityInThePipeline:
    """A figure the passages do not contain, caught without a model call."""

    _INVENTED = json.dumps({
        "answer": "Training converged in 9 epochs.",
        "claims": [{"text": "Training converged in 9 epochs.", "citations": ["[S1]"]}],
        "insufficient_evidence": False,
    })
    _CORRECTED = json.dumps({
        "answer": "Training converged in 12 epochs.",
        "claims": [{"text": "Training converged in 12 epochs.", "citations": ["[S1]"]}],
        "insufficient_evidence": False,
    })

    def _evidence(self) -> list[Evidence]:
        return [_ev("Training converged in 12 epochs.", label="[S1]")]

    async def test_an_invented_figure_triggers_a_repair(self) -> None:
        """Nothing else in the pipeline objects: the claim is entailed and the prose
        matches it. Only the figure is one the passage never wrote."""
        calls = 0

        def _stream(_req: object) -> _FakeTokenStream:
            nonlocal calls
            calls += 1
            return _FakeTokenStream(self._INVENTED if calls == 1 else self._CORRECTED, None)

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=_stream)

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()), gateway=gateway
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]

        assert gateway.generate_stream.call_count == 2
        assert collected == ["Training converged in 12 epochs."]

    async def test_the_repair_instructions_quote_the_invented_figure(self) -> None:
        calls = 0

        def _stream(_req: object) -> _FakeTokenStream:
            nonlocal calls
            calls += 1
            return _FakeTokenStream(self._INVENTED if calls == 1 else self._CORRECTED, None)

        gateway = MagicMock()
        gateway.generate_stream = MagicMock(side_effect=_stream)

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()), gateway=gateway
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        checklist = " ".join(gateway.generate_stream.call_args_list[1].args[0].critical_checklist)
        assert "9" in checklist
        assert "without rounding or converting" in checklist

    async def test_an_answer_whose_figures_match_passes_straight_through(self) -> None:
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._CORRECTED, None)
        )

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()), gateway=gateway
        ).execute(_BASE_CMD)
        collected = [t async for t in stream]

        assert gateway.generate_stream.call_count == 1
        assert collected == ["Training converged in 12 epochs."]

    async def test_a_persistently_invented_figure_is_refused(self) -> None:
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._INVENTED, None)
        )

        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()), gateway=gateway
        ).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass


class TestGenerationRules:
    """The rules the prompt carries, one per §38 requirement that binds here."""

    @staticmethod
    async def _requirements() -> str:
        gateway = _mock_gateway()
        stream = await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        async for _ in stream:
            pass
        request = gateway.generate_stream.call_args.args[0]
        return " ".join(r.rendered for r in request.mandatory_requirements)

    async def test_history_is_declared_not_to_be_evidence(self) -> None:
        text = await self._requirements()
        assert "never as a source a claim can rest on" in text

    async def test_figures_are_required_to_survive_verbatim(self) -> None:
        text = await self._requirements()
        assert "exactly as the passage" in text
        assert "Do not round, convert, rescale" in text

    async def test_source_fact_is_separated_from_model_inference(self) -> None:
        text = await self._requirements()
        assert "which are your own reasoning" in text

    async def test_the_three_new_rules_bind_critically(self) -> None:
        """A preference can be shed under budget pressure; a grounding rule cannot."""
        gateway = _mock_gateway()
        stream = await _make_use_case(gateway=gateway).execute(_BASE_CMD)
        async for _ in stream:
            pass

        request = gateway.generate_stream.call_args.args[0]
        grounding = [
            r
            for r in request.mandatory_requirements
            if r.instruction.category is InstructionCategory.GROUNDING_AND_SOURCE_USE
        ]
        assert len(grounding) == 5
        assert all(r.instruction.level is RequirementLevel.CRITICAL for r in grounding)


class TestPartialAbstention:
    """A question the material half covers, answered by halves rather than refused."""

    _MIXED = json.dumps({
        "answer": "Gradients flow backwards, and the optimiser is Adam.",
        "claims": [
            {"text": "Gradients flow backwards.", "citations": ["[S1]"]},
            {"text": "The optimiser is Adam.", "citations": ["[S2]"]},
        ],
        "insufficient_evidence": False,
    })

    def _evidence(self) -> list[Evidence]:
        return [
            _ev("Gradients flow backwards.", label="[S1]"),
            _ev("Something about learning rates.", label="[S2]"),
        ]

    @staticmethod
    def _split_entailment() -> MagicMock:
        """[S1] supports its claim; [S2] does not address the one that cites it."""

        async def _check(claim: object, passages: list[object]) -> tuple[EntailmentResult, ...]:
            return tuple(
                EntailmentResult(
                    claim=claim,  # type: ignore[arg-type]
                    passage_label=p.label,  # type: ignore[union-attr]
                    status=(
                        ClaimStatus.ENTAILED
                        if p.label == "[S1]"  # type: ignore[union-attr]
                        else ClaimStatus.NOT_SUPPORTED
                    ),
                )
                for p in passages
            )

        entailment = MagicMock()
        entailment.check_claim = AsyncMock(side_effect=_check)
        return entailment

    async def _run(self) -> list[str]:
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._MIXED, None)
        )
        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            entailment=self._split_entailment(),
        ).execute(_BASE_CMD)
        return [t async for t in stream]

    async def test_the_supported_half_is_answered_rather_than_withheld(self) -> None:
        collected = await self._run()
        assert collected[0].startswith("Gradients flow backwards.")

    async def test_the_unsupported_half_is_named(self) -> None:
        collected = await self._run()
        assert "The optimiser is Adam." in collected[0]
        assert "could not find support" in collected[0]

    async def test_only_the_surviving_claim_is_cited(self) -> None:
        repo = _mock_repo()
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._MIXED, None)
        )
        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            repo=repo,
            gateway=gateway,
            entailment=self._split_entailment(),
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        saved = list(repo.save_citations.call_args.args[2])
        assert [c.label.bracketed for c in saved] == ["[S1]"]

    async def test_the_turn_is_recorded_as_completed(self) -> None:
        repo = _mock_repo()
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._MIXED, None)
        )
        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            repo=repo,
            gateway=gateway,
            entailment=self._split_entailment(),
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assistant: Message = repo.save_message.call_args_list[1].args[1]
        assert assistant.status is MessageStatus.COMPLETED

    async def test_a_contradiction_is_still_refused(self) -> None:
        """Salvage handles gaps, not misreadings."""
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._MIXED, None)
        )
        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            entailment=_mock_entailment(ClaimStatus.CONTRADICTED),
        ).execute(_BASE_CMD)
        with pytest.raises(GenerationRejectedError):
            async for _ in stream:
                pass

    async def test_salvage_runs_only_after_the_repair_was_spent(self) -> None:
        """One repair, then salvage — never salvage in place of the repair."""
        gateway = MagicMock()
        gateway.generate_stream = MagicMock(
            side_effect=lambda _req: _FakeTokenStream(self._MIXED, None)
        )
        stream = await _make_use_case(
            retrieve=_mock_retrieve(self._evidence()),
            gateway=gateway,
            entailment=self._split_entailment(),
        ).execute(_BASE_CMD)
        async for _ in stream:
            pass

        assert gateway.generate_stream.call_count == 2
