"""Tests for memory context injection in AnswerUseCase.

Verifies that active memory facts are loaded from the repository and placed
into the correct prompt slots (pinned_memory vs relevant_memory) based on
provenance. All other AnswerUseCase behaviour is covered in test_answer_use_case.py.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.application.commands.answer import AnswerCommand, AnswerUseCase
from app.application.queries.retrieve_evidence import RetrievalResult
from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.memory.entities import MemoryFact
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


def _make_fact(
    *,
    key: str,
    value: dict,
    provenance: MemoryProvenance,
) -> MemoryFact:
    return MemoryFact(
        id=uuid.uuid4(),
        user_id=_SCOPE.user_id,
        knowledge_base_id=_SCOPE.knowledge_base_id,
        memory_type=MemoryType.GOAL,
        key=key,
        value=value,
        confidence=0.9,
        provenance=provenance,
        status=MemoryStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
        valid_from=_NOW,
    )


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


def _mock_memory_repo(
    facts: list[MemoryFact],
    dense_results: list[tuple[MemoryFact, float]] | None = None,
) -> AsyncMock:
    repo = AsyncMock()
    repo.list_active = AsyncMock(return_value=facts)
    repo.dense_search = AsyncMock(return_value=dense_results if dense_results is not None else [])
    return repo


def _make_use_case(
    *,
    memory_repo: AsyncMock | None = None,
    gateway: MagicMock | None = None,
    embedder: AsyncMock | None = None,
) -> tuple[AnswerUseCase, MagicMock]:
    captured_gateway = gateway or _mock_gateway()
    conv_repo = _mock_conv_repo()

    uc = AnswerUseCase(
        retrieve=_mock_retrieve(),
        conversation_uow=lambda: _uow(conv_repo),
        model_gateway=captured_gateway,
        context_builder=_context_builder(),
        entailment=AsyncMock(),
        faithfulness=AsyncMock(),
        memory_repo=memory_repo,
        embedder=embedder,
    )
    return uc, captured_gateway


# ---------------------------------------------------------------------------
# No memory repo wired
# ---------------------------------------------------------------------------


class TestNoMemoryRepo:
    async def test_empty_memory_slots_when_no_repo(self) -> None:
        uc, gw = _make_use_case(memory_repo=None)
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert request.pinned_memory == ()
        assert request.relevant_memory == ()


# ---------------------------------------------------------------------------
# Memory repo wired but no active facts
# ---------------------------------------------------------------------------


class TestNoActiveFacts:
    async def test_empty_slots_when_repo_returns_no_facts(self) -> None:
        uc, gw = _make_use_case(memory_repo=_mock_memory_repo([]))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert request.pinned_memory == ()
        assert request.relevant_memory == ()


# ---------------------------------------------------------------------------
# Provenance routing
# ---------------------------------------------------------------------------


class TestProvenanceRouting:
    async def test_user_statement_fact_goes_to_pinned_memory(self) -> None:
        fact = _make_fact(
            key="exam_date",
            value={"date": "2026-12-01"},
            provenance=MemoryProvenance.USER_STATEMENT,
        )
        uc, gw = _make_use_case(memory_repo=_mock_memory_repo([fact]))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert len(request.pinned_memory) == 1
        assert request.relevant_memory == ()
        assert "exam_date" in request.pinned_memory[0]

    async def test_user_correction_fact_goes_to_pinned_memory(self) -> None:
        fact = _make_fact(
            key="exam_date",
            value={"date": "2026-12-15"},
            provenance=MemoryProvenance.USER_CORRECTION,
        )
        uc, gw = _make_use_case(memory_repo=_mock_memory_repo([fact]))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert len(request.pinned_memory) == 1
        assert request.relevant_memory == ()

    async def test_assistant_inference_fact_goes_to_relevant_memory(self) -> None:
        fact = _make_fact(
            key="weak_topic",
            value={"topic": "thermodynamics"},
            provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        )
        uc, gw = _make_use_case(memory_repo=_mock_memory_repo([fact]))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert request.pinned_memory == ()
        assert len(request.relevant_memory) == 1
        assert "weak_topic" in request.relevant_memory[0]

    async def test_application_event_fact_goes_to_relevant_memory(self) -> None:
        fact = _make_fact(
            key="sessions_completed",
            value={"count": 5},
            provenance=MemoryProvenance.APPLICATION_EVENT,
        )
        uc, gw = _make_use_case(memory_repo=_mock_memory_repo([fact]))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert request.pinned_memory == ()
        assert len(request.relevant_memory) == 1

    async def test_mixed_provenance_split_correctly(self) -> None:
        facts = [
            _make_fact(
                key="exam_date",
                value={"date": "2026-12-01"},
                provenance=MemoryProvenance.USER_STATEMENT,
            ),
            _make_fact(
                key="weak_topic",
                value={"topic": "thermodynamics"},
                provenance=MemoryProvenance.ASSISTANT_INFERENCE,
            ),
            _make_fact(
                key="study_goal",
                value={"text": "pass with distinction"},
                provenance=MemoryProvenance.USER_CORRECTION,
            ),
        ]
        uc, gw = _make_use_case(memory_repo=_mock_memory_repo(facts))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert len(request.pinned_memory) == 2
        assert len(request.relevant_memory) == 1


# ---------------------------------------------------------------------------
# Content format
# ---------------------------------------------------------------------------


class TestContentFormat:
    async def test_fact_content_uses_key_colon_value_format(self) -> None:
        fact = _make_fact(
            key="exam_date",
            value={"date": "2026-12-01"},
            provenance=MemoryProvenance.USER_STATEMENT,
        )
        expected = fact.content  # "exam_date: {\"date\": \"2026-12-01\"}"

        uc, gw = _make_use_case(memory_repo=_mock_memory_repo([fact]))
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert request.pinned_memory[0] == expected


# ---------------------------------------------------------------------------
# Semantic search path (embedder wired)
# ---------------------------------------------------------------------------


def _mock_embedder(embedding: list[float] | None = None) -> AsyncMock:
    emb = AsyncMock()
    emb.embed_query = AsyncMock(return_value=embedding or [0.1, 0.2, 0.3])
    return emb


class TestSemanticSearch:
    async def test_embed_query_called_with_command_query(self) -> None:
        fact = _make_fact(
            key="weak_topic",
            value={"topic": "thermodynamics"},
            provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        )
        embedder = _mock_embedder()
        repo = _mock_memory_repo([fact], dense_results=[(fact, 0.1)])
        uc, _ = _make_use_case(memory_repo=repo, embedder=embedder)
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="what is heat transfer?")
        await uc.execute(cmd)
        embedder.embed_query.assert_awaited_once_with("what is heat transfer?")

    async def test_dense_search_called_with_embedding(self) -> None:
        fact = _make_fact(
            key="weak_topic",
            value={"topic": "thermodynamics"},
            provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        )
        embedding = [0.5, 0.6, 0.7]
        embedder = _mock_embedder(embedding)
        repo = _mock_memory_repo([fact], dense_results=[(fact, 0.1)])
        uc, _ = _make_use_case(memory_repo=repo, embedder=embedder)
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        repo.dense_search.assert_awaited_once()
        call_args = repo.dense_search.call_args
        assert call_args[0][1] == embedding

    async def test_dense_results_go_to_relevant_memory(self) -> None:
        fact = _make_fact(
            key="weak_topic",
            value={"topic": "thermodynamics"},
            provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        )
        embedder = _mock_embedder()
        repo = _mock_memory_repo([fact], dense_results=[(fact, 0.1)])
        uc, gw = _make_use_case(memory_repo=repo, embedder=embedder)
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert len(request.relevant_memory) == 1
        assert "weak_topic" in request.relevant_memory[0]

    async def test_pinned_facts_always_present_with_embedder(self) -> None:
        pinned_fact = _make_fact(
            key="exam_date",
            value={"date": "2026-12-01"},
            provenance=MemoryProvenance.USER_STATEMENT,
        )
        inferred_fact = _make_fact(
            key="weak_topic",
            value={"topic": "thermodynamics"},
            provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        )
        embedder = _mock_embedder()
        repo = _mock_memory_repo(
            [pinned_fact, inferred_fact],
            dense_results=[(inferred_fact, 0.1)],
        )
        uc, gw = _make_use_case(memory_repo=repo, embedder=embedder)
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        assert len(request.pinned_memory) == 1
        assert len(request.relevant_memory) == 1

    async def test_fallback_to_list_active_when_dense_returns_empty(self) -> None:
        fact = _make_fact(
            key="weak_topic",
            value={"topic": "thermodynamics"},
            provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        )
        embedder = _mock_embedder()
        # dense_search returns empty (no embeddings stored yet)
        repo = _mock_memory_repo([fact], dense_results=[])
        uc, gw = _make_use_case(memory_repo=repo, embedder=embedder)
        cmd = AnswerCommand(scope=_SCOPE, conversation_id=_CONV_ID, query="q")
        await uc.execute(cmd)
        request = gw.generate_stream.call_args[0][0]
        # Fallback: the inferred fact still appears via list_active
        assert len(request.relevant_memory) == 1
