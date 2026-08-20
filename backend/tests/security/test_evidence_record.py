"""Security tests: the record of what the model was given must match what it was given.

Citation validation asks one question — did the passage this answer cites actually
reach the model, or did the model invent a reference to something it never saw? That
question is answerable only against a stored record, because the prompt is gone by the
time anyone asks. If the record and the prompt can disagree, a fabricated citation can
be validated against a passage that was never in context, and the check silently passes
whatever it was built to catch.

So the invariant is equality in both directions, not containment:

  1. Every passage in the prompt is recorded — a missing row makes a genuine citation
     look fabricated.

  2. Nothing is recorded that was not in the prompt — a spurious row makes a fabricated
     citation look genuine. This is the dangerous direction.

  3. The record carries the caller's scope and nothing else, so an evidence set that
     somehow spanned two Knowledge Bases could not be written as though it belonged
     to one.

These use real Chunk and Evidence objects rather than mocks, because the invariant is
precisely that the text placed in the prompt and the id written to the record come from
the same chunk. Mock objects would let those two drift apart and still pass.

Run with: uv run pytest -m security
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
from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, RetrieverKind
from app.domain.errors import ScopeViolationError
from app.domain.models.context_builder import ContextBuilder
from app.domain.retrieval.entities import Evidence, EvidenceLabel
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText
from app.infrastructure.database.repositories.conversation import SqlConversationRepository

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())

# Valid answer with no claims — the pipeline returns INSUFFICIENT_EVIDENCE immediately,
# so these tests exercise the evidence-record path without needing a real entailment mock.
_VALID_JSON = json.dumps({
    "answer": "The retrieved passages do not cover this topic.",
    "claims": [],
    "insufficient_evidence": True,
})
_CONV_ID = uuid.uuid4()
_COMMAND = AnswerCommand(
    scope=_SCOPE,
    conversation_id=_CONV_ID,
    query="What is backpropagation?",
)


# ---------------------------------------------------------------------------
# Factories — real domain objects, so chunk text and chunk id cannot diverge
# ---------------------------------------------------------------------------


def _chunk(text: str, *, scope: ScopeContext = _SCOPE, ordinal: int = 0) -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        user_id=scope.user_id,
        knowledge_base_id=scope.knowledge_base_id,
        document_id=uuid.uuid4(),
        chunk_type=ChunkType.TEXT,
        text=UntrustedText(text),
        token_count=max(1, len(text) // 4),
        ordinal=ordinal,
        page_start=1,
        page_end=1,
        index_version=1,
        created_at=datetime.now(UTC),
    )


def _evidence(text: str, *, scope: ScopeContext = _SCOPE, rank: int = 0) -> Evidence:
    return Evidence(
        label=EvidenceLabel(rank + 1),
        chunk=_chunk(text, scope=scope, ordinal=rank),
        retrievers=frozenset({RetrieverKind.DENSE}),
        rank=rank,
        rerank_score=-10.0 + rank,
    )


def _use_case(evidence: list[Evidence], repo: AsyncMock, gateway: MagicMock) -> AnswerUseCase:
    retrieve = AsyncMock()
    retrieve.execute = AsyncMock(return_value=evidence)

    entailment = AsyncMock()
    entailment.check_claim = AsyncMock(return_value=())

    @asynccontextmanager
    async def _uow() -> AsyncIterator[AsyncMock]:
        yield repo

    return AnswerUseCase(
        retrieve=retrieve,
        conversation_uow=_uow,
        model_gateway=gateway,
        context_builder=ContextBuilder(lambda text: len(text.split()), token_budget=100_000),
        entailment=entailment,
    )


def _repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_history = AsyncMock(return_value=[])
    repo.list_messages = AsyncMock(return_value=[])
    repo.save_message = AsyncMock()
    repo.save_retrieval_chunks = AsyncMock()
    return repo


def _gateway(tokens: list[str] | None = None) -> MagicMock:
    async def _gen() -> AsyncIterator[str]:
        for token in tokens or [_VALID_JSON]:
            yield token

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(return_value=_gen())
    return gateway


async def _answer(evidence: list[Evidence], repo: AsyncMock, gateway: MagicMock) -> None:
    """Run one full turn to completion, discarding the tokens."""
    stream = await _use_case(evidence, repo, gateway).execute(_COMMAND)
    async for _ in stream:
        pass


def _prompt_passages(gateway: MagicMock) -> tuple[str, ...]:
    request = gateway.generate_stream.call_args.args[0]
    return tuple(passage.text.value for passage in request.evidence)


def _recorded(repo: AsyncMock) -> list[Evidence]:
    return list(repo.save_retrieval_chunks.call_args.args[2])


# ---------------------------------------------------------------------------
# 1. Every passage in the prompt is recorded
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_every_prompt_passage_has_a_recorded_chunk() -> None:
    """A passage the model saw but nobody recorded makes a real citation look invented."""
    repo, gateway = _repo(), _gateway()
    evidence = [_evidence(f"Passage {i}", rank=i) for i in range(5)]

    await _answer(evidence, repo, gateway)

    recorded_texts = {item.chunk.text.value for item in _recorded(repo)}
    assert set(_prompt_passages(gateway)) <= recorded_texts


@pytest.mark.security
@pytest.mark.gate
async def test_record_is_exactly_the_prompt_set() -> None:
    """Equality in both directions — containment either way would leave a gap."""
    repo, gateway = _repo(), _gateway()
    evidence = [_evidence(f"Passage {i}", rank=i) for i in range(5)]

    await _answer(evidence, repo, gateway)

    recorded_texts = sorted(item.chunk.text.value for item in _recorded(repo))
    assert recorded_texts == sorted(_prompt_passages(gateway))


# ---------------------------------------------------------------------------
# 2. Nothing is recorded that was not in the prompt
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_no_chunk_is_recorded_beyond_the_prompt_set() -> None:
    """A recorded passage the model never saw is what lets a fabricated citation pass."""
    repo, gateway = _repo(), _gateway()
    evidence = [_evidence(f"Passage {i}", rank=i) for i in range(3)]

    await _answer(evidence, repo, gateway)

    assert len(_recorded(repo)) == len(_prompt_passages(gateway))


@pytest.mark.security
@pytest.mark.gate
async def test_a_chunk_retrieval_did_not_return_never_appears_in_the_record() -> None:
    """Existing in the Knowledge Base is not the same as having been put in front of
    the model. Only what retrieval selected may be recorded."""
    repo, gateway = _repo(), _gateway()
    retrieved = [_evidence("Retrieved passage", rank=0)]
    # Same user, same Knowledge Base, simply not selected for this turn.
    never_retrieved = _chunk("Some other passage in the same Knowledge Base")

    await _answer(retrieved, repo, gateway)

    recorded_ids = {item.chunk.id for item in _recorded(repo)}
    assert never_retrieved.id not in recorded_ids


@pytest.mark.security
@pytest.mark.gate
async def test_empty_retrieval_records_nothing() -> None:
    """Answering without evidence must not leave a record implying there was some."""
    repo, gateway = _repo(), _gateway()

    await _answer([], repo, gateway)

    assert _recorded(repo) == []
    assert _prompt_passages(gateway) == ()


# ---------------------------------------------------------------------------
# 3. Scope
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_record_is_written_under_the_calling_scope() -> None:
    repo, gateway = _repo(), _gateway()

    await _answer([_evidence("Passage")], repo, gateway)

    assert repo.save_retrieval_chunks.call_args.args[0] == _SCOPE


@pytest.mark.security
@pytest.mark.gate
async def test_every_recorded_chunk_belongs_to_the_calling_scope() -> None:
    """The record must never attribute another Knowledge Base's chunk to this answer."""
    repo, gateway = _repo(), _gateway()
    evidence = [_evidence(f"Passage {i}", rank=i) for i in range(3)]

    await _answer(evidence, repo, gateway)

    for item in _recorded(repo):
        assert item.chunk.user_id == _SCOPE.user_id
        assert item.chunk.knowledge_base_id == _SCOPE.knowledge_base_id


@pytest.mark.security
@pytest.mark.gate
async def test_repository_refuses_a_record_written_under_a_foreign_scope() -> None:
    """The write is refused before it reaches the database, not filtered afterwards."""
    bound_scope = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
    foreign_scope = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
    session = AsyncMock()

    repository = SqlConversationRepository(scope=bound_scope, session=session)

    with pytest.raises(ScopeViolationError):
        await repository.save_retrieval_chunks(
            foreign_scope, uuid.uuid4(), [_evidence("Passage", scope=foreign_scope)]
        )

    session.merge.assert_not_called()


# ---------------------------------------------------------------------------
# 4. The record survives the paths where it matters most
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.gate
async def test_record_is_written_when_generation_fails_partway() -> None:
    """A half-streamed answer can still carry a citation, so it still needs an audit trail."""

    async def _failing() -> AsyncIterator[str]:
        yield "The answer is"
        raise RuntimeError("provider dropped the connection")

    gateway = MagicMock()
    gateway.generate_stream = MagicMock(return_value=_failing())
    repo = _repo()
    evidence = [_evidence(f"Passage {i}", rank=i) for i in range(3)]

    stream = await _use_case(evidence, repo, gateway).execute(_COMMAND)
    with pytest.raises(RuntimeError):
        async for _ in stream:
            pass

    recorded_texts = sorted(item.chunk.text.value for item in _recorded(repo))
    assert recorded_texts == sorted(_prompt_passages(gateway))


@pytest.mark.security
@pytest.mark.gate
async def test_two_answers_in_one_conversation_keep_separate_records() -> None:
    """Evidence from an earlier turn must not be attributed to a later answer."""
    repo = _repo()

    first_evidence = [_evidence("First turn passage")]
    await _answer(first_evidence, repo, _gateway())

    second_evidence = [_evidence(f"Second turn passage {i}", rank=i) for i in range(2)]
    await _answer(second_evidence, repo, _gateway())

    first_call, second_call = repo.save_retrieval_chunks.call_args_list
    first_message_id, second_message_id = first_call.args[1], second_call.args[1]

    assert first_message_id != second_message_id
    assert list(first_call.args[2]) == first_evidence
    assert list(second_call.args[2]) == second_evidence
