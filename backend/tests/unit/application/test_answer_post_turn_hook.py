"""Tests for post-turn memory extraction wiring in AnswerUseCase.

Verifies that AnswerUseCase calls the post_turn_hook exactly when the turn
completes successfully, and that it is silent (logs, does not re-raise) when
the hook raises.  Execution logic of the hook itself is tested separately in
test_post_turn_hook_builder.py.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.application.queries.retrieve_evidence import RetrievalResult
from app.domain.models.context_builder import ContextBuilder
from app.domain.scope import ScopeContext

_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_CONV_ID = uuid.uuid4()

_ANSWER_JSON = json.dumps({
    "answer": "Test answer.",
    "claims": [],
    "insufficient_evidence": True,
})


def _mock_retrieve() -> AsyncMock:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(
        return_value=RetrievalResult(
            evidence=[], standalone_query="q", was_rewritten=False
        )
    )
    return retrieve


def _mock_conv_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    repo.save_citations = AsyncMock()
    conv = MagicMock()
    conv.rolling_summary = None
    repo.get = AsyncMock(return_value=conv)
    return repo


@asynccontextmanager
async def _uow(repo: AsyncMock) -> AsyncIterator[AsyncMock]:
    yield repo


def _mock_gateway() -> MagicMock:
    class _Stream:
        async def __aiter__(self) -> AsyncIterator[str]:
            yield _ANSWER_JSON

        @property
        def usage(self):
            return None

    gw = MagicMock()
    gw.generate_stream = MagicMock(return_value=_Stream())
    return gw


def _context_builder() -> ContextBuilder:
    return ContextBuilder(lambda t: len(t.split()), token_budget=100_000)


def _make_use_case(
    *,
    hook: AsyncMock | None = None,
    gateway: MagicMock | None = None,
) -> AnswerUseCase:
    conv_repo = _mock_conv_repo()
    return AnswerUseCase(
        retrieve=_mock_retrieve(),
        conversation_uow=lambda: _uow(conv_repo),
        model_gateway=gateway or _mock_gateway(),
        context_builder=_context_builder(),
        entailment=AsyncMock(),
        faithfulness=AsyncMock(),
        post_turn_hook=hook,
    )


async def _consume(uc: AnswerUseCase) -> None:
    gen = await uc.execute(AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q"))
    async for _ in gen:
        pass


# ---------------------------------------------------------------------------
# Hook fires on COMPLETED turns
# ---------------------------------------------------------------------------


class TestHookFiring:
    async def test_hook_called_once_on_completed_turn(self) -> None:
        hook = AsyncMock()
        uc = _make_use_case(hook=hook)
        await _consume(uc)
        hook.assert_awaited_once()

    async def test_hook_receives_scope(self) -> None:
        hook = AsyncMock()
        uc = _make_use_case(hook=hook)
        await _consume(uc)
        args = hook.call_args[0]
        assert args[0] is _SCOPE

    async def test_hook_receives_uuid_as_second_arg(self) -> None:
        hook = AsyncMock()
        uc = _make_use_case(hook=hook)
        await _consume(uc)
        args = hook.call_args[0]
        assert isinstance(args[1], uuid.UUID)

    async def test_no_hook_does_not_raise(self) -> None:
        uc = _make_use_case(hook=None)
        await _consume(uc)  # must complete without error


# ---------------------------------------------------------------------------
# Hook is NOT called on failed turns
# ---------------------------------------------------------------------------


class TestHookNotCalledOnFailure:
    async def test_hook_not_called_when_generation_raises(self) -> None:
        class _BrokenStream:
            async def __aiter__(self) -> AsyncIterator[str]:
                raise RuntimeError("model error")
                yield  # make it an async generator

            @property
            def usage(self):
                return None

        gw = MagicMock()
        gw.generate_stream = MagicMock(return_value=_BrokenStream())
        hook = AsyncMock()
        uc = _make_use_case(hook=hook, gateway=gw)

        gen = await uc.execute(AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q"))
        with pytest.raises(RuntimeError):
            async for _ in gen:
                pass

        hook.assert_not_awaited()


# ---------------------------------------------------------------------------
# Hook errors are swallowed (logged, not re-raised)
# ---------------------------------------------------------------------------


class TestHookErrorSuppression:
    async def test_hook_exception_does_not_propagate(self) -> None:
        hook = AsyncMock(side_effect=Exception("hook boom"))
        uc = _make_use_case(hook=hook)
        # Should complete without raising the hook's exception
        await _consume(uc)
