"""Unit tests for ExtractMemoryUseCase.

All external dependencies (conversation repo, memory repo, extraction port) are
mocked. Tests verify orchestration logic — no LLM or database involved.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.application.commands.extract_memory import (
    ExtractMemoryCommand,
    ExtractMemoryUseCase,
)
from app.domain.enums import (
    MemoryProvenance,
    MemoryStatus,
    MemoryType,
    MessageRole,
    MessageStatus,
)
from app.domain.errors import MemoryExtractionError
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _make_scope() -> ScopeContext:
    return ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())


def _make_fact(scope: ScopeContext, *, key: str = "exam_date") -> MemoryFact:
    return MemoryFact(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        memory_type=MemoryType.EXAM_DATE,
        key=key,
        value={"date": "2026-12-01"},
        confidence=0.9,
        provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        status=MemoryStatus.ACTIVE,
        created_at=NOW,
        updated_at=NOW,
        valid_from=NOW,
    )


def _make_message(scope: ScopeContext, *, role: MessageRole, conversation_id: uuid.UUID) -> MagicMock:
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.conversation_id = conversation_id
    msg.user_id = scope.user_id
    msg.knowledge_base_id = scope.knowledge_base_id
    msg.role = role
    msg.status = MessageStatus.COMPLETED
    msg.content = MagicMock()
    msg.content.value = "sample text"
    return msg


def _use_case(
    *,
    assistant_msg: Any | None = None,
    messages: list[Any] | None = None,
    active_facts: list[MemoryFact] | None = None,
    candidates: list[MemoryFact] | None = None,
    extractor_raises: type[Exception] | None = None,
) -> tuple[ExtractMemoryUseCase, AsyncMock, AsyncMock]:
    conv_repo = AsyncMock()
    conv_repo.get_message = AsyncMock(return_value=assistant_msg)
    conv_repo.list_messages = AsyncMock(return_value=messages or [])

    memory_repo = AsyncMock()
    memory_repo.list_active = AsyncMock(return_value=active_facts or [])
    memory_repo.save_batch = AsyncMock()

    extractor = AsyncMock()
    if extractor_raises is not None:
        extractor.extract = AsyncMock(side_effect=extractor_raises("boom"))
    else:
        extractor.extract = AsyncMock(return_value=candidates or [])

    uc = ExtractMemoryUseCase(
        conversation_repo=conv_repo,
        memory_repo=memory_repo,
        extractor=extractor,
    )
    return uc, memory_repo, extractor


# ---------------------------------------------------------------------------
# Early-exit conditions
# ---------------------------------------------------------------------------


class TestEarlyExit:
    async def test_returns_zero_when_message_not_found(self) -> None:
        scope = _make_scope()
        uc, repo, _ = _use_case(assistant_msg=None)
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=uuid.uuid4()))
        assert result.created == 0
        assert result.superseded == 0
        repo.save_batch.assert_not_called()

    async def test_returns_zero_when_message_is_not_assistant_role(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        uc, repo, _ = _use_case(assistant_msg=user_msg)
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=user_msg.id))
        assert result.created == 0
        repo.save_batch.assert_not_called()

    async def test_returns_zero_when_message_is_not_completed(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        msg.status = MessageStatus.FAILED
        uc, repo, _ = _use_case(assistant_msg=msg)
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=msg.id))
        assert result.created == 0
        repo.save_batch.assert_not_called()

    async def test_returns_zero_when_no_preceding_user_message(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED
        # Only the assistant message in history — no user message precedes it.
        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg],
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 0
        repo.save_batch.assert_not_called()

    async def test_returns_zero_when_extractor_raises(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED
        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            extractor_raises=MemoryExtractionError,
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 0
        repo.save_batch.assert_not_called()

    async def test_returns_zero_when_extractor_returns_empty(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED
        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            candidates=[],
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 0
        repo.save_batch.assert_not_called()


# ---------------------------------------------------------------------------
# New fact creation
# ---------------------------------------------------------------------------


class TestNewFactCreation:
    async def test_saves_candidate_when_no_existing_fact_for_key(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED
        candidate = _make_fact(scope, key="exam_date")
        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            active_facts=[],
            candidates=[candidate],
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 1
        assert result.superseded == 0
        assert candidate.id in result.embeddable_ids
        repo.save_batch.assert_awaited_once()
        saved = repo.save_batch.call_args[0][1]
        assert len(saved) == 1
        assert saved[0].key == "exam_date"

    async def test_saves_multiple_new_candidates(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED
        candidates = [
            _make_fact(scope, key="exam_date"),
            _make_fact(scope, key="weak_topic"),
        ]
        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            active_facts=[],
            candidates=candidates,
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 2
        assert result.superseded == 0


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------


class TestSupersession:
    async def test_creates_successor_when_key_already_exists(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED

        existing = MemoryFact(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            memory_type=MemoryType.EXAM_DATE,
            key="exam_date",
            value={"date": "2026-11-01"},
            confidence=0.8,
            provenance=MemoryProvenance.USER_STATEMENT,
            status=MemoryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            valid_from=NOW,
        )
        candidate = _make_fact(scope, key="exam_date")

        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            active_facts=[existing],
            candidates=[candidate],
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 0
        assert result.superseded == 1
        saved = repo.save_batch.call_args[0][1]
        # retired + successor
        assert len(saved) == 2
        statuses = {f.status for f in saved}
        assert MemoryStatus.SUPERSEDED in statuses
        assert MemoryStatus.ACTIVE in statuses

    async def test_embeddable_ids_contains_successor_not_retired(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED

        existing = MemoryFact(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            memory_type=MemoryType.EXAM_DATE,
            key="exam_date",
            value={"date": "2026-11-01"},
            confidence=0.8,
            provenance=MemoryProvenance.USER_STATEMENT,
            status=MemoryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            valid_from=NOW,
        )
        candidate = _make_fact(scope, key="exam_date")

        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            active_facts=[existing],
            candidates=[candidate],
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        # The successor (candidate.id) must be embedded; the retired fact (existing.id) must not.
        assert candidate.id in result.embeddable_ids
        assert existing.id not in result.embeddable_ids

    async def test_successor_inherits_key_from_existing_fact(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED

        existing = MemoryFact(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            memory_type=MemoryType.EXAM_DATE,
            key="exam_date",
            value={"date": "2026-11-01"},
            confidence=0.8,
            provenance=MemoryProvenance.USER_STATEMENT,
            status=MemoryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            valid_from=NOW,
        )
        candidate = _make_fact(scope, key="exam_date")

        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            active_facts=[existing],
            candidates=[candidate],
        )
        await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        saved = repo.save_batch.call_args[0][1]
        successor = next(f for f in saved if f.status is MemoryStatus.ACTIVE)
        assert successor.key == "exam_date"
        assert successor.id == candidate.id

    async def test_mixed_new_and_superseded(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED

        existing = MemoryFact(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            knowledge_base_id=scope.knowledge_base_id,
            memory_type=MemoryType.EXAM_DATE,
            key="exam_date",
            value={"date": "2026-11-01"},
            confidence=0.8,
            provenance=MemoryProvenance.USER_STATEMENT,
            status=MemoryStatus.ACTIVE,
            created_at=NOW,
            updated_at=NOW,
            valid_from=NOW,
        )
        candidates = [
            _make_fact(scope, key="exam_date"),   # supersedes existing
            _make_fact(scope, key="weak_topic"),  # brand new
        ]

        uc, repo, _ = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            active_facts=[existing],
            candidates=candidates,
        )
        result = await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))
        assert result.created == 1
        assert result.superseded == 1
        # 2 from supersession (retired + successor) + 1 new = 3
        saved = repo.save_batch.call_args[0][1]
        assert len(saved) == 3


# ---------------------------------------------------------------------------
# Extractor receives the right turn text
# ---------------------------------------------------------------------------


class TestExtractorInput:
    async def test_passes_correct_message_text_to_extractor(self) -> None:
        scope = _make_scope()
        conv_id = uuid.uuid4()
        user_msg = _make_message(scope, role=MessageRole.USER, conversation_id=conv_id)
        user_msg.content.value = "When is my biology exam?"
        assistant_msg = _make_message(scope, role=MessageRole.ASSISTANT, conversation_id=conv_id)
        assistant_msg.status = MessageStatus.COMPLETED
        assistant_msg.content.value = "Your biology exam is on December 1st."

        uc, _, extractor = _use_case(
            assistant_msg=assistant_msg,
            messages=[assistant_msg, user_msg],
            candidates=[],
        )
        await uc.execute(ExtractMemoryCommand(scope=scope, message_id=assistant_msg.id))

        extractor.extract.assert_awaited_once()
        call_kwargs = extractor.extract.call_args.kwargs
        assert call_kwargs["user_message"] == "When is my biology exam?"
        assert call_kwargs["assistant_message"] == "Your biology exam is on December 1st."
        assert call_kwargs["source_message_id"] == assistant_msg.id
