"""Unit tests for AnswerUseCase answer-cache logic (step 16.2).

Covers:
  _answer_cache_key
    - Same inputs produce the same key (determinism).
    - Query change, history change, index_version change, policy change, KB change
      each produce a different key (sensitivity).
    - Key is prefixed with 'answer:<kb_id>:'.

  AnswerUseCase.execute with cache wired
    - Cache hit: retrieval is skipped; cached text is yielded.
    - Cache miss: retrieval runs; answer is written to cache on COMPLETED.
    - Cache write skipped when the stream raises during collection (outcome=FAILED).
    - Cache is not called when cache=None (default).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.commands.answer import (
    AnswerCommand,
    AnswerUseCase,
    _answer_cache_key,
)
from app.application.queries.retrieve_evidence import RetrievalResult
from app.domain.conversations.entities import Conversation
from app.domain.enums import AnswerFidelity, MessageRole
from app.domain.models.context_builder import ContextBuilder
from app.domain.models.entities import ConversationTurn
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 1, 1, tzinfo=UTC)
_USER = uuid.uuid4()
_KB = uuid.uuid4()
_SCOPE = ScopeContext(user_id=_USER, knowledge_base_id=_KB)
_CONV_ID = uuid.uuid4()

# An abstention is the easiest valid response: insufficient_evidence=True + claims=[].
# It is *returnable* (ValidationDecision.INSUFFICIENT_EVIDENCE.is_returnable == True),
# so the generator yields the "answer" field and the outcome is COMPLETED — abstentions
# are cached the same as any other answer.
_ABSTAIN_JSON = json.dumps(
    {"answer": "I don't know.", "claims": [], "insufficient_evidence": True}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _history(*pairs: tuple[str, str]) -> tuple[ConversationTurn, ...]:
    """Build a history tuple; role strings must be 'USER' or 'ASSISTANT'."""
    return tuple(
        ConversationTurn(role=MessageRole(role), content=UntrustedText(text))
        for role, text in pairs
    )


def _mock_cache(hit: bytes | None = None) -> AsyncMock:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=hit)
    cache.put = AsyncMock()
    return cache


def _mock_retrieve() -> AsyncMock:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(
        return_value=RetrievalResult(evidence=[], standalone_query="q", was_rewritten=False)
    )
    return retrieve


def _mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    repo.save_citations = AsyncMock()
    repo.get = AsyncMock(
        return_value=Conversation(
            id=_CONV_ID,
            user_id=_USER,
            knowledge_base_id=_KB,
            title="t",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    return repo


@asynccontextmanager
async def _uow_over(repo: AsyncMock) -> AsyncIterator[AsyncMock]:
    yield repo


def _uow(repo: AsyncMock):
    def _factory():
        return _uow_over(repo)
    return _factory


class _FakeStream:
    """A model stream that immediately yields a single JSON chunk."""

    def __init__(self, chunk: str) -> None:
        self._chunk = chunk
        self.usage = None

    async def __aiter__(self) -> AsyncIterator[str]:
        yield self._chunk


class _ErrorStream:
    """A model stream that raises during iteration, simulating a generation failure."""

    usage = None

    async def __aiter__(self) -> AsyncIterator[str]:
        raise RuntimeError("model down")
        yield  # make Python recognise this as a generator


def _mock_gateway(response: str = _ABSTAIN_JSON) -> MagicMock:
    gw = MagicMock()
    gw.generate_stream = MagicMock(side_effect=lambda _r: _FakeStream(response))
    return gw


def _mock_gateway_error() -> MagicMock:
    """Gateway whose stream raises RuntimeError during iteration (inside _tracked)."""
    gw = MagicMock()
    gw.generate_stream = MagicMock(return_value=_ErrorStream())
    return gw


def _mock_entailment() -> MagicMock:
    e = MagicMock()
    e.check_claim = AsyncMock(return_value=())
    return e


def _mock_faithfulness() -> MagicMock:
    f = MagicMock()
    f.check_answer = AsyncMock(return_value=AnswerFidelity.FAITHFUL)
    return f


def _context_builder() -> ContextBuilder:
    return ContextBuilder(lambda text: len(text.split()), token_budget=100_000)


def _make_use_case(
    *,
    retrieve: AsyncMock | None = None,
    repo: AsyncMock | None = None,
    gateway: MagicMock | None = None,
    cache: AsyncMock | None = None,
    cache_ttl_seconds: int = 3600,
    index_version: int = 1,
    generation_policy_version: int = 1,
) -> AnswerUseCase:
    _repo = repo or _mock_repo()
    return AnswerUseCase(
        retrieve=retrieve or _mock_retrieve(),
        conversation_uow=_uow(_repo),
        model_gateway=gateway or _mock_gateway(),
        context_builder=_context_builder(),
        entailment=_mock_entailment(),
        faithfulness=_mock_faithfulness(),
        cache=cache,
        cache_ttl_seconds=cache_ttl_seconds,
        index_version=index_version,
        generation_policy_version=generation_policy_version,
    )


def _cmd(query: str = "What is 42?") -> AnswerCommand:
    return AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query=query)


# ---------------------------------------------------------------------------
# _answer_cache_key
# ---------------------------------------------------------------------------


class TestAnswerCacheKey:
    def test_same_inputs_same_key(self) -> None:
        hist = _history(("USER", "hi"))
        k1 = _answer_cache_key(_SCOPE, "q", hist, 1, 1)
        k2 = _answer_cache_key(_SCOPE, "q", hist, 1, 1)
        assert k1 == k2

    def test_different_query_different_key(self) -> None:
        hist = _history()
        k1 = _answer_cache_key(_SCOPE, "q1", hist, 1, 1)
        k2 = _answer_cache_key(_SCOPE, "q2", hist, 1, 1)
        assert k1 != k2

    def test_different_history_different_key(self) -> None:
        k1 = _answer_cache_key(_SCOPE, "q", _history(("USER", "prev")), 1, 1)
        k2 = _answer_cache_key(_SCOPE, "q", _history(), 1, 1)
        assert k1 != k2

    def test_different_index_version_different_key(self) -> None:
        hist = _history()
        k1 = _answer_cache_key(_SCOPE, "q", hist, 1, 1)
        k2 = _answer_cache_key(_SCOPE, "q", hist, 2, 1)
        assert k1 != k2

    def test_different_generation_policy_different_key(self) -> None:
        hist = _history()
        k1 = _answer_cache_key(_SCOPE, "q", hist, 1, 1)
        k2 = _answer_cache_key(_SCOPE, "q", hist, 1, 2)
        assert k1 != k2

    def test_different_kb_different_key(self) -> None:
        hist = _history()
        scope_a = ScopeContext(user_id=_USER, knowledge_base_id=uuid.uuid4())
        scope_b = ScopeContext(user_id=_USER, knowledge_base_id=uuid.uuid4())
        k1 = _answer_cache_key(scope_a, "q", hist, 1, 1)
        k2 = _answer_cache_key(scope_b, "q", hist, 1, 1)
        assert k1 != k2

    def test_key_prefixed_with_answer_and_kb_id(self) -> None:
        k = _answer_cache_key(_SCOPE, "q", _history(), 1, 1)
        assert k.startswith(f"answer:{_KB}:")


# ---------------------------------------------------------------------------
# Cache hit — retrieval skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_yields_cached_text() -> None:
    cache = _mock_cache(hit=b"cached answer text")
    use_case = _make_use_case(cache=cache)

    gen = await use_case.execute(_cmd())
    tokens = [t async for t in gen]

    assert tokens == ["cached answer text"]


@pytest.mark.asyncio
async def test_cache_hit_skips_retrieval() -> None:
    retrieve = _mock_retrieve()
    cache = _mock_cache(hit=b"cached")
    use_case = _make_use_case(retrieve=retrieve, cache=cache)

    gen = await use_case.execute(_cmd())
    async for _ in gen:
        pass

    retrieve.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cache miss — retrieval runs and answer is written to cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_runs_retrieval() -> None:
    retrieve = _mock_retrieve()
    cache = _mock_cache(hit=None)
    use_case = _make_use_case(retrieve=retrieve, cache=cache)

    gen = await use_case.execute(_cmd())
    async for _ in gen:
        pass

    retrieve.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_miss_writes_answer_to_cache() -> None:
    # The abstention response ("I don't know.") is still returnable and cached.
    cache = _mock_cache(hit=None)
    use_case = _make_use_case(cache=cache)

    gen = await use_case.execute(_cmd())
    results = [t async for t in gen]

    assert results == ["I don't know."]
    cache.put.assert_awaited_once()
    _key, _data = cache.put.call_args.args[:2]
    assert _data == b"I don't know."
    assert _key.startswith(f"answer:{_KB}:")


@pytest.mark.asyncio
async def test_cache_write_uses_configured_ttl() -> None:
    cache = _mock_cache(hit=None)
    use_case = _make_use_case(cache=cache, cache_ttl_seconds=9999)

    gen = await use_case.execute(_cmd())
    async for _ in gen:
        pass

    ttl_arg = cache.put.call_args.kwargs.get("ttl")
    assert ttl_arg == 9999


# ---------------------------------------------------------------------------
# No cache write when stream raises during generation (outcome=FAILED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_error_skips_cache_write() -> None:
    """When the model stream raises during collection, outcome=FAILED and cache.put is skipped."""
    cache = _mock_cache(hit=None)
    use_case = _make_use_case(cache=cache, gateway=_mock_gateway_error())

    gen = await use_case.execute(_cmd())
    with pytest.raises(RuntimeError, match="model down"):
        async for _ in gen:
            pass

    cache.put.assert_not_awaited()


# ---------------------------------------------------------------------------
# No cache at all (cache=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_cache_runs_retrieval_normally() -> None:
    retrieve = _mock_retrieve()
    use_case = _make_use_case(retrieve=retrieve, cache=None)

    gen = await use_case.execute(_cmd())
    async for _ in gen:
        pass

    retrieve.execute.assert_awaited_once()
