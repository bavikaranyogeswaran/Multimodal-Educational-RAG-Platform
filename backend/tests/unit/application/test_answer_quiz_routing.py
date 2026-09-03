"""Tests for QUIZ_GENERATION routing in AnswerUseCase.

Verifies that when the query classifier returns QUIZ_GENERATION, the use case
routes to GenerateQuizUseCase instead of the standard answer path. All other
AnswerUseCase behaviour is covered in test_answer_use_case.py.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.application.commands.generate_quiz import GenerateQuizCommand, QuizResult
from app.application.queries.retrieve_evidence import RetrievalResult
from app.domain.enums import QueryClass
from app.domain.models.context_builder import ContextBuilder
from app.domain.scope import ScopeContext

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_CONV_ID = uuid.uuid4()

_FALLBACK_ANSWER_JSON = json.dumps({
    "answer": "Standard answer.",
    "claims": [],
    "insufficient_evidence": True,
})

_QUIZ_TEXT = "1. What is entropy?\n   Answer: A measure of disorder."


def _mock_retrieve(query_class: QueryClass = QueryClass.QUIZ_GENERATION) -> AsyncMock:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(
        return_value=RetrievalResult(
            evidence=[],
            standalone_query="quiz me",
            was_rewritten=False,
            query_class=query_class,
        )
    )
    return retrieve


def _mock_conv_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    return repo


@asynccontextmanager
async def _uow(repo: AsyncMock) -> AsyncIterator[AsyncMock]:
    yield repo


def _mock_gateway() -> MagicMock:
    class _Stream:
        async def __aiter__(self) -> AsyncIterator[str]:
            yield _FALLBACK_ANSWER_JSON

        @property
        def usage(self):
            return None

    gw = MagicMock()
    gw.generate_stream = MagicMock(return_value=_Stream())
    return gw


def _mock_quiz_generator(text: str = _QUIZ_TEXT) -> AsyncMock:
    gen = AsyncMock()
    gen.execute = AsyncMock(return_value=QuizResult(text=text))
    return gen


def _context_builder() -> ContextBuilder:
    return ContextBuilder(lambda t: len(t.split()), token_budget=100_000)


def _make_use_case(
    *,
    retrieve: AsyncMock | None = None,
    quiz_generator: AsyncMock | None = None,
    conv_repo: AsyncMock | None = None,
) -> tuple[AnswerUseCase, AsyncMock, AsyncMock]:
    repo = conv_repo or _mock_conv_repo()
    gen = quiz_generator if quiz_generator is not None else _mock_quiz_generator()
    uc = AnswerUseCase(
        retrieve=retrieve or _mock_retrieve(),
        conversation_uow=lambda: _uow(repo),
        model_gateway=_mock_gateway(),
        context_builder=_context_builder(),
        entailment=AsyncMock(),
        faithfulness=AsyncMock(),
        quiz_generator=gen,
    )
    return uc, gen, repo


# ---------------------------------------------------------------------------
# Quiz path activated
# ---------------------------------------------------------------------------


class TestQuizRouting:
    async def test_quiz_generator_called_when_query_class_is_quiz_generation(self) -> None:
        uc, gen, _ = _make_use_case()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="quiz me on chapter 3")
        stream = await uc.execute(cmd)
        _ = [t async for t in stream]
        gen.execute.assert_awaited_once()

    async def test_quiz_generator_receives_query_and_scope(self) -> None:
        uc, gen, _ = _make_use_case()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="quiz me on chapter 3")
        stream = await uc.execute(cmd)
        _ = [t async for t in stream]

        call_args = gen.execute.call_args[0][0]
        assert isinstance(call_args, GenerateQuizCommand)
        assert call_args.scope == _SCOPE
        assert call_args.query == "quiz me on chapter 3"

    async def test_yielded_token_is_quiz_text(self) -> None:
        uc, _, _ = _make_use_case()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="quiz me")
        stream = await uc.execute(cmd)
        tokens = [t async for t in stream]
        assert tokens == [_QUIZ_TEXT]

    async def test_quiz_text_saved_as_assistant_message_content(self) -> None:
        uc, _, repo = _make_use_case()
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="quiz me")
        stream = await uc.execute(cmd)
        _ = [t async for t in stream]

        # The final save_message call (after the stream is consumed) stores the quiz text.
        final_save = repo.save_message.call_args_list[-1]
        saved_msg = final_save[0][1]
        assert saved_msg.content.value == _QUIZ_TEXT


# ---------------------------------------------------------------------------
# Quiz generator not wired — falls back to standard path
# ---------------------------------------------------------------------------


class TestNoQuizGenerator:
    async def test_standard_path_used_when_quiz_generator_is_none(self) -> None:
        repo = _mock_conv_repo()
        uc = AnswerUseCase(
            retrieve=_mock_retrieve(QueryClass.QUIZ_GENERATION),
            conversation_uow=lambda: _uow(repo),
            model_gateway=_mock_gateway(),
            context_builder=_context_builder(),
            entailment=AsyncMock(),
            faithfulness=AsyncMock(),
            quiz_generator=None,
        )
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="quiz me")
        stream = await uc.execute(cmd)
        tokens = [t async for t in stream]
        # Standard path yields the answer from the JSON envelope.
        assert "Standard answer." in "".join(tokens)


# ---------------------------------------------------------------------------
# Non-quiz query class — quiz generator not called
# ---------------------------------------------------------------------------


class TestQuizGeneratorIgnoredForOtherClasses:
    async def test_quiz_generator_not_called_for_direct_query(self) -> None:
        uc, gen, _ = _make_use_case(
            retrieve=_mock_retrieve(QueryClass.DIRECT),
        )
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="what is entropy?")
        stream = await uc.execute(cmd)
        _ = [t async for t in stream]
        gen.execute.assert_not_called()
