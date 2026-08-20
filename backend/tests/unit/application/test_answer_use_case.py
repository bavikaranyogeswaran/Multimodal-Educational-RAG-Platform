"""Unit tests for AnswerUseCase."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.application.queries.retrieve_evidence import RetrieveEvidenceQuery
from app.domain.conversations.entities import Message
from app.domain.enums import (
    ClaimStatus,
    InstructionCategory,
    MessageRole,
    MessageStatus,
    ModelTask,
    RequirementLevel,
)
from app.domain.errors import GenerationRejectedError
from app.domain.models.context_builder import ContextBuilder
from app.domain.models.validation import EntailmentResult
from app.domain.ports.repositories import ConversationUnitOfWork
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


def _ev(text: str, *, label: str = "[S1]") -> MagicMock:
    ev = MagicMock()
    ev.chunk.text = UntrustedText(text)
    ev.label.bracketed = label
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


def _mock_retrieve(evidence: list[MagicMock] | None = None) -> AsyncMock:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(return_value=evidence or [])
    return retrieve


def _mock_repo(messages: list[Message] | None = None) -> AsyncMock:
    repo = AsyncMock()
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


def _recording_retrieve(call_order: list[str]) -> Callable[..., list[MagicMock]]:
    """Note that retrieval ran, then return no evidence."""

    def _record(*_args: object, **_kwargs: object) -> list[MagicMock]:
        call_order.append("retrieve")
        return []

    return _record


def _mock_gateway(response: str | None = None) -> MagicMock:
    """Return a gateway whose generate_stream yields a single JSON chunk.

    The default is a valid insufficient_evidence answer so tests that do not care
    about validation pass without needing real evidence or an entailment mock.
    Passing a custom string lets tests exercise specific validation paths.
    """
    chunk = response if response is not None else _VALID_ANSWER_JSON

    async def _gen() -> AsyncIterator[str]:
        yield chunk

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(return_value=_gen())
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


def _context_builder() -> ContextBuilder:
    """A real builder, generous enough that nothing under test ever gets shed.

    What the builder does with a tight budget is its own module's concern; here the
    interest is only in what AnswerUseCase hands it and does with what it returns.
    """
    return ContextBuilder(lambda text: len(text.split()), token_budget=100_000)


def _make_use_case(
    retrieve: AsyncMock | None = None,
    repo: AsyncMock | None = None,
    gateway: MagicMock | None = None,
    opened: list[str] | None = None,
    context_builder: ContextBuilder | None = None,
    entailment: MagicMock | None = None,
) -> AnswerUseCase:
    return AnswerUseCase(
        retrieve=retrieve or _mock_retrieve(),
        conversation_uow=_uow_over(repo or _mock_repo(), opened),
        model_gateway=gateway or _mock_gateway(),
        context_builder=context_builder or _context_builder(),
        entailment=entailment or _mock_entailment(),
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
