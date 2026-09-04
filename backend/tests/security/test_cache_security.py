"""Security tests: the answer cache is scoped to the authenticated user.

Two invariants:

  1. The cache key includes both user_id and knowledge_base_id — two users asking
     the same question against the same Knowledge Base get different cache entries.

  2. A cache entry seeded under user A's key is not reachable from user B's request —
     user B always hits the model and never receives user A's cached content.

Run with: uv run pytest -m "security and gate"
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.answer import (
    AnswerCommand,
    AnswerUseCase,
    _answer_cache_key,
)
from app.application.queries.retrieve_evidence import RetrievalResult
from app.domain.enums import AnswerFidelity
from app.domain.models.context_builder import ContextBuilder
from app.domain.scope import ScopeContext

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_KB_ID = uuid.uuid4()
_USER_A = uuid.uuid4()
_USER_B = uuid.uuid4()

_SCOPE_A = ScopeContext(user_id=_USER_A, knowledge_base_id=_KB_ID)
_SCOPE_B = ScopeContext(user_id=_USER_B, knowledge_base_id=_KB_ID)
_SCOPE_OTHER_KB = ScopeContext(user_id=_USER_A, knowledge_base_id=uuid.uuid4())

_QUERY = "What is gradient descent?"

_CACHED_ANSWER = json.dumps({
    "answer": "Cached answer for user A.",
    "claims": [],
    "insufficient_evidence": True,
})
_CACHED_BYTES = _CACHED_ANSWER.encode("utf-8")

_FRESH_ANSWER = json.dumps({
    "answer": "A fresh answer for user B.",
    "claims": [],
    "insufficient_evidence": True,
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    repo.list_messages = AsyncMock(return_value=[])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    conv = MagicMock()
    conv.rolling_summary = None
    repo.get = AsyncMock(return_value=conv)
    return repo


def _use_case(gateway: MagicMock, cache: AsyncMock) -> AnswerUseCase:
    faithfulness = AsyncMock()
    faithfulness.check_answer = AsyncMock(return_value=AnswerFidelity.FAITHFUL)

    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(
        return_value=RetrievalResult(
            evidence=[],
            standalone_query=_QUERY,
            was_rewritten=False,
        )
    )

    entailment = MagicMock()
    entailment.check_claim = AsyncMock(return_value=())

    @asynccontextmanager
    async def _uow() -> AsyncIterator[AsyncMock]:
        yield _repo()

    return AnswerUseCase(
        retrieve=retrieve,
        conversation_uow=_uow,
        model_gateway=gateway,
        context_builder=ContextBuilder(lambda text: len(text.split()), token_budget=100_000),
        entailment=entailment,
        faithfulness=faithfulness,
        cache=cache,
        index_version=1,
        generation_policy_version=1,
    )


# ---------------------------------------------------------------------------
# Gate tests — 6th release gate: unauthorized cache reuse
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_cache_key_differs_by_user() -> None:
    """Same query, same KB, different users produce different cache keys.

    Both user_id and knowledge_base_id must participate in the key derivation
    so that two users with identical queries never share a cache entry.
    """
    key_a = _answer_cache_key(_SCOPE_A, _QUERY, (), 1, 1)
    key_b = _answer_cache_key(_SCOPE_B, _QUERY, (), 1, 1)
    assert key_a != key_b


@pytest.mark.security
@pytest.mark.gate
async def test_cache_key_differs_by_kb() -> None:
    """Same query, same user, different Knowledge Bases produce different cache keys."""
    key_a = _answer_cache_key(_SCOPE_A, _QUERY, (), 1, 1)
    key_other_kb = _answer_cache_key(_SCOPE_OTHER_KB, _QUERY, (), 1, 1)
    assert key_a != key_other_kb


@pytest.mark.security
@pytest.mark.gate
async def test_user_cannot_retrieve_another_users_cached_answer() -> None:
    """User B's request is a cache miss when only user A's key is populated.

    The model must be invoked for user B, and the text cached under user A's
    key must not appear anywhere in user B's response stream.
    """
    key_a = _answer_cache_key(_SCOPE_A, _QUERY, (), 1, 1)

    cache = AsyncMock()
    cache.get = AsyncMock(side_effect=lambda k: _CACHED_BYTES if k == key_a else None)
    cache.put = AsyncMock()

    async def _gen() -> AsyncIterator[str]:
        yield _FRESH_ANSWER

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(return_value=_gen())

    command = AnswerCommand(
        scope=_SCOPE_B,
        conversation_id=uuid.uuid4(),
        query=_QUERY,
    )

    chunks: list[str] = []
    stream = await _use_case(gateway, cache).execute(command)
    async for chunk in stream:
        chunks.append(chunk)

    response_text = "".join(chunks)

    assert gateway.generate_stream.call_count == 1, (
        "model was not invoked — user B incorrectly received a cache hit from user A's key"
    )
    assert "Cached answer for user A" not in response_text, (
        "user A's cached content appeared in user B's response — unauthorized cache reuse"
    )
