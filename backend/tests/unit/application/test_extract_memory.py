"""Unit tests for ExtractMemoryUseCase.

Covers the per-key lookup path introduced when list_active was replaced with
get_active_by_key: for each candidate the use case now asks the repository
whether an active fact with that key already exists, and creates a supersession
pair when one does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.extract_memory import (
    ExtractMemoryCommand,
    ExtractMemoryResult,
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
from app.domain.values import UntrustedText

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _active_fact(key: str = "exam_date") -> MemoryFact:
    return MemoryFact(
        id=uuid.uuid4(),
        user_id=_SCOPE.user_id,
        knowledge_base_id=_SCOPE.knowledge_base_id,
        memory_type=MemoryType.EXAM_DATE,
        key=key,
        value={"date": "2026-12-01"},
        confidence=0.9,
        provenance=MemoryProvenance.USER_STATEMENT,
        status=MemoryStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
    )


def _candidate(key: str = "exam_date") -> MemoryFact:
    return MemoryFact(
        id=uuid.uuid4(),
        user_id=_SCOPE.user_id,
        knowledge_base_id=_SCOPE.knowledge_base_id,
        memory_type=MemoryType.EXAM_DATE,
        key=key,
        value={"date": "2027-01-15"},
        confidence=0.8,
        provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        status=MemoryStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
    )


def _make_message(
    *,
    msg_id: uuid.UUID,
    conv_id: uuid.UUID,
    role: MessageRole,
    status: MessageStatus = MessageStatus.COMPLETED,
    content: str = "some text",
) -> MagicMock:
    msg = MagicMock()
    msg.id = msg_id
    msg.conversation_id = conv_id
    msg.role = role
    msg.status = status
    msg.content = UntrustedText(content)
    return msg


def _setup(
    *,
    existing: MemoryFact | None = None,
    candidates: list[MemoryFact] | None = None,
    assistant_role: MessageRole = MessageRole.ASSISTANT,
    assistant_status: MessageStatus = MessageStatus.COMPLETED,
    no_user_msg: bool = False,
    message_not_found: bool = False,
) -> tuple[ExtractMemoryUseCase, ExtractMemoryCommand]:
    """Build a use case and the matching command with all IDs wired together."""
    asst_id = uuid.uuid4()
    conv_id = uuid.uuid4()

    asst_msg = _make_message(
        msg_id=asst_id,
        conv_id=conv_id,
        role=assistant_role,
        status=assistant_status,
        content="assistant answer",
    )
    user_msg = _make_message(
        msg_id=uuid.uuid4(),
        conv_id=conv_id,
        role=MessageRole.USER,
        content="user question",
    )

    conv_repo = AsyncMock()
    conv_repo.get_message = AsyncMock(
        return_value=None if message_not_found else asst_msg
    )
    history = [] if no_user_msg else [asst_msg, user_msg]
    conv_repo.list_messages = AsyncMock(return_value=history)

    mem_repo = AsyncMock()
    mem_repo.get_active_by_key = AsyncMock(return_value=existing)
    mem_repo.save_batch = AsyncMock()

    ext = AsyncMock()
    ext.extract = AsyncMock(return_value=candidates or [])

    uc = ExtractMemoryUseCase(
        conversation_repo=conv_repo,
        memory_repo=mem_repo,
        extractor=ext,
    )
    cmd = ExtractMemoryCommand(scope=_SCOPE, message_id=asst_id)
    return uc, cmd


# ---------------------------------------------------------------------------
# no-op cases
# ---------------------------------------------------------------------------


class TestNoOps:
    async def test_message_not_found_returns_zero(self) -> None:
        uc, cmd = _setup(message_not_found=True)
        assert await uc.execute(cmd) == ExtractMemoryResult(created=0, superseded=0)

    async def test_wrong_role_returns_zero(self) -> None:
        uc, cmd = _setup(assistant_role=MessageRole.USER)
        assert await uc.execute(cmd) == ExtractMemoryResult(created=0, superseded=0)

    async def test_incomplete_status_returns_zero(self) -> None:
        uc, cmd = _setup(assistant_status=MessageStatus.FAILED)
        assert await uc.execute(cmd) == ExtractMemoryResult(created=0, superseded=0)

    async def test_no_preceding_user_message_returns_zero(self) -> None:
        uc, cmd = _setup(no_user_msg=True)
        assert await uc.execute(cmd) == ExtractMemoryResult(created=0, superseded=0)

    async def test_empty_candidates_returns_zero(self) -> None:
        uc, cmd = _setup(candidates=[])
        assert await uc.execute(cmd) == ExtractMemoryResult(created=0, superseded=0)

    async def test_extractor_error_returns_zero(self) -> None:
        uc, cmd = _setup()
        uc._extractor.extract = AsyncMock(side_effect=MemoryExtractionError("bad"))
        assert await uc.execute(cmd) == ExtractMemoryResult(created=0, superseded=0)


# ---------------------------------------------------------------------------
# new fact (no existing active key)
# ---------------------------------------------------------------------------


class TestNewFact:
    async def test_new_fact_increments_created(self) -> None:
        candidate = _candidate("learning_goal")
        uc, cmd = _setup(candidates=[candidate], existing=None)
        result = await uc.execute(cmd)
        assert result.created == 1
        assert result.superseded == 0

    async def test_new_fact_id_in_embeddable_ids(self) -> None:
        candidate = _candidate("learning_goal")
        uc, cmd = _setup(candidates=[candidate], existing=None)
        result = await uc.execute(cmd)
        assert candidate.id in result.embeddable_ids

    async def test_new_fact_saved_via_save_batch(self) -> None:
        candidate = _candidate("learning_goal")
        uc, cmd = _setup(candidates=[candidate], existing=None)
        await uc.execute(cmd)
        uc._memory_repo.save_batch.assert_awaited_once()
        saved = uc._memory_repo.save_batch.call_args[0][1]
        assert candidate in saved

    async def test_uses_get_active_by_key_not_list_active(self) -> None:
        candidate = _candidate("exam_date")
        uc, cmd = _setup(candidates=[candidate], existing=None)
        await uc.execute(cmd)
        uc._memory_repo.get_active_by_key.assert_awaited_once_with(_SCOPE, "exam_date")


# ---------------------------------------------------------------------------
# supersession (existing active key)
# ---------------------------------------------------------------------------


class TestSupersession:
    async def test_existing_key_increments_superseded(self) -> None:
        candidate = _candidate("exam_date")
        uc, cmd = _setup(candidates=[candidate], existing=_active_fact("exam_date"))
        result = await uc.execute(cmd)
        assert result.superseded == 1
        assert result.created == 0

    async def test_successor_id_in_embeddable_ids(self) -> None:
        candidate = _candidate("exam_date")
        uc, cmd = _setup(candidates=[candidate], existing=_active_fact("exam_date"))
        result = await uc.execute(cmd)
        assert candidate.id in result.embeddable_ids

    async def test_save_batch_receives_retired_and_successor(self) -> None:
        candidate = _candidate("exam_date")
        uc, cmd = _setup(candidates=[candidate], existing=_active_fact("exam_date"))
        await uc.execute(cmd)
        saved = uc._memory_repo.save_batch.call_args[0][1]
        statuses = {f.status for f in saved}
        assert MemoryStatus.SUPERSEDED in statuses
        assert MemoryStatus.ACTIVE in statuses

    async def test_retired_fact_points_to_successor(self) -> None:
        candidate = _candidate("exam_date")
        uc, cmd = _setup(candidates=[candidate], existing=_active_fact("exam_date"))
        await uc.execute(cmd)
        saved = uc._memory_repo.save_batch.call_args[0][1]
        retired = next(f for f in saved if f.status == MemoryStatus.SUPERSEDED)
        assert retired.superseded_by == candidate.id


# ---------------------------------------------------------------------------
# multiple candidates — per-key lookup called once per candidate
# ---------------------------------------------------------------------------


class TestMultipleCandidates:
    async def test_mixed_new_and_superseded(self) -> None:
        existing = _active_fact("exam_date")
        uc, cmd = _setup(
            candidates=[_candidate("exam_date"), _candidate("learning_goal")],
        )
        # "exam_date" exists; "learning_goal" does not
        uc._memory_repo.get_active_by_key = AsyncMock(
            side_effect=lambda scope, key: existing if key == "exam_date" else None
        )
        result = await uc.execute(cmd)
        assert result.created == 1
        assert result.superseded == 1
        assert len(result.embeddable_ids) == 2

    async def test_get_active_by_key_called_once_per_candidate(self) -> None:
        uc, cmd = _setup(
            candidates=[_candidate("goal"), _candidate("weak_topic")],
            existing=None,
        )
        await uc.execute(cmd)
        assert uc._memory_repo.get_active_by_key.await_count == 2
