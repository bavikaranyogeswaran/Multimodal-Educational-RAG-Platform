"""Unit tests for CompactMemoryUseCase."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.compact_memory import (
    CompactMemoryCommand,
    CompactMemoryResult,
    CompactMemoryUseCase,
)
from app.domain.conversations.entities import Conversation
from app.domain.enums import MessageRole, MessageStatus
from app.domain.conversations.entities import Message
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
_CONV_ID = uuid.uuid4()


def _make_conversation(*, rolling_summary: str | None = None) -> Conversation:
    return Conversation(
        id=_CONV_ID,
        user_id=_SCOPE.user_id,
        knowledge_base_id=_SCOPE.knowledge_base_id,
        title="Test conversation",
        created_at=_NOW,
        updated_at=_NOW,
        rolling_summary=rolling_summary,
    )


def _make_message(content: str, role: MessageRole = MessageRole.ASSISTANT) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=_CONV_ID,
        user_id=_SCOPE.user_id,
        knowledge_base_id=_SCOPE.knowledge_base_id,
        role=role,
        status=MessageStatus.COMPLETED,
        content=UntrustedText(content),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _use_case(
    *,
    conversation: Conversation | None,
    messages: list[Message],
    summary_return: str = "Summarized content.",
    min_messages: int = 3,
) -> tuple[CompactMemoryUseCase, AsyncMock, AsyncMock]:
    conv_repo = AsyncMock()
    conv_repo.get = AsyncMock(return_value=conversation)
    conv_repo.list_history = AsyncMock(return_value=messages)
    conv_repo.save = AsyncMock()

    summarizer = AsyncMock()
    summarizer.summarize = AsyncMock(return_value=summary_return)

    use_case = CompactMemoryUseCase(
        conversation_repo=conv_repo,
        summarizer=summarizer,
        min_messages=min_messages,
    )
    return use_case, conv_repo, summarizer


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_written_when_count_at_threshold() -> None:
    conv = _make_conversation()
    msgs = [_make_message(f"msg {i}") for i in range(5)]
    uc, conv_repo, summarizer = _use_case(conversation=conv, messages=msgs, min_messages=5)

    result = await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    assert result.summary_written is True
    summarizer.summarize.assert_awaited_once()
    conv_repo.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_skipped_below_threshold() -> None:
    conv = _make_conversation()
    msgs = [_make_message("msg") for _ in range(2)]
    uc, conv_repo, summarizer = _use_case(conversation=conv, messages=msgs, min_messages=5)

    result = await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    assert result.summary_written is False
    summarizer.summarize.assert_not_awaited()
    conv_repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_false_when_conversation_not_found() -> None:
    msgs: list[Message] = []
    uc, conv_repo, summarizer = _use_case(conversation=None, messages=msgs, min_messages=1)

    result = await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    assert result.summary_written is False
    summarizer.summarize.assert_not_awaited()
    conv_repo.list_history.assert_not_awaited()


@pytest.mark.asyncio
async def test_passes_previous_summary_to_summarizer() -> None:
    prior = "Prior summary text."
    conv = _make_conversation(rolling_summary=prior)
    msgs = [_make_message(f"msg {i}") for i in range(3)]
    uc, _, summarizer = _use_case(conversation=conv, messages=msgs, min_messages=3)

    await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    _, kwargs = summarizer.summarize.call_args
    assert kwargs["previous_summary"] == prior


@pytest.mark.asyncio
async def test_passes_none_previous_summary_when_no_prior() -> None:
    conv = _make_conversation(rolling_summary=None)
    msgs = [_make_message(f"msg {i}") for i in range(3)]
    uc, _, summarizer = _use_case(conversation=conv, messages=msgs, min_messages=3)

    await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    _, kwargs = summarizer.summarize.call_args
    assert kwargs["previous_summary"] is None


@pytest.mark.asyncio
async def test_turns_in_chronological_order() -> None:
    """list_history returns newest first; the use case must reverse before summarizing."""
    conv = _make_conversation()
    # Simulate repo returning most-recent-first
    msgs = [_make_message(f"msg {i}") for i in range(3, 0, -1)]  # [3, 2, 1]
    uc, _, summarizer = _use_case(conversation=conv, messages=msgs, min_messages=3)

    await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    _, kwargs = summarizer.summarize.call_args
    turns = kwargs["turns"]
    assert turns == ["msg 1", "msg 2", "msg 3"]


@pytest.mark.asyncio
async def test_saves_updated_conversation() -> None:
    new_summary = "Fresh summary."
    conv = _make_conversation()
    msgs = [_make_message(f"msg {i}") for i in range(3)]
    uc, conv_repo, _ = _use_case(
        conversation=conv, messages=msgs, summary_return=new_summary, min_messages=3
    )

    await uc.execute(CompactMemoryCommand(scope=_SCOPE, conversation_id=_CONV_ID))

    saved: Conversation = conv_repo.save.call_args[0][1]
    assert saved.rolling_summary == new_summary
