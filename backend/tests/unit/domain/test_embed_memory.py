"""Unit tests for EmbedMemoryUseCase.

All external dependencies are mocked. Tests verify:
  - empty fact_ids list returns immediately without calling the embedder
  - missing facts are counted and skipped, not raised
  - content strings are batched into a single embed_documents call
  - vectors are written back via update_embedding per fact
  - correct counts in EmbedMemoryResult
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, call

from app.application.commands.embed_memory import (
    EmbedMemoryCommand,
    EmbedMemoryUseCase,
)
from app.domain.enums import MemoryProvenance, MemoryStatus, MemoryType
from app.domain.memory.entities import MemoryFact
from app.domain.scope import ScopeContext

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
_EMBEDDING_DIM = 384


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
        confidence=0.85,
        provenance=MemoryProvenance.ASSISTANT_INFERENCE,
        status=MemoryStatus.UNCONFIRMED,
        created_at=NOW,
        updated_at=NOW,
        valid_from=NOW,
    )


def _mock_embedder(vectors: list[list[float]] | None = None) -> MagicMock:
    embedder = MagicMock()
    embedder.dimension = _EMBEDDING_DIM
    if vectors is None:
        vectors = [[0.1] * _EMBEDDING_DIM]
    embedder.embed_documents = AsyncMock(return_value=vectors)
    return embedder


def _use_case(
    *,
    facts_by_id: dict[uuid.UUID, MemoryFact | None] | None = None,
    embedder: MagicMock | None = None,
) -> tuple[EmbedMemoryUseCase, AsyncMock, MagicMock]:
    memory_repo = AsyncMock()
    memory_repo.get = AsyncMock(
        side_effect=lambda scope, fact_id: (facts_by_id or {}).get(fact_id)
    )
    memory_repo.update_embedding = AsyncMock()

    emb = embedder or _mock_embedder()
    uc = EmbedMemoryUseCase(memory_repo=memory_repo, embedder=emb)
    return uc, memory_repo, emb


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    async def test_returns_zero_for_empty_ids(self) -> None:
        scope = _make_scope()
        uc, repo, emb = _use_case()
        result = await uc.execute(EmbedMemoryCommand(scope=scope, fact_ids=[]))
        assert result.embedded == 0
        assert result.missing == 0
        emb.embed_documents.assert_not_called()
        repo.update_embedding.assert_not_called()


# ---------------------------------------------------------------------------
# Missing facts
# ---------------------------------------------------------------------------


class TestMissingFacts:
    async def test_missing_fact_is_counted_not_raised(self) -> None:
        scope = _make_scope()
        missing_id = uuid.uuid4()
        uc, repo, emb = _use_case(facts_by_id={missing_id: None})
        result = await uc.execute(
            EmbedMemoryCommand(scope=scope, fact_ids=[missing_id])
        )
        assert result.missing == 1
        assert result.embedded == 0
        emb.embed_documents.assert_not_called()

    async def test_found_facts_embedded_despite_some_missing(self) -> None:
        scope = _make_scope()
        present = _make_fact(scope, key="exam_date")
        missing_id = uuid.uuid4()
        vector = [0.5] * _EMBEDDING_DIM
        uc, repo, emb = _use_case(
            facts_by_id={present.id: present, missing_id: None},
            embedder=_mock_embedder([[0.5] * _EMBEDDING_DIM]),
        )
        result = await uc.execute(
            EmbedMemoryCommand(scope=scope, fact_ids=[present.id, missing_id])
        )
        assert result.embedded == 1
        assert result.missing == 1


# ---------------------------------------------------------------------------
# Embedding and writing
# ---------------------------------------------------------------------------


class TestEmbeddingAndWriting:
    async def test_passes_content_string_to_embedder(self) -> None:
        scope = _make_scope()
        fact = _make_fact(scope, key="exam_date")
        vector = [0.1] * _EMBEDDING_DIM
        uc, repo, emb = _use_case(
            facts_by_id={fact.id: fact},
            embedder=_mock_embedder([vector]),
        )
        await uc.execute(EmbedMemoryCommand(scope=scope, fact_ids=[fact.id]))
        emb.embed_documents.assert_awaited_once_with([fact.content])

    async def test_batches_all_contents_in_one_embed_call(self) -> None:
        scope = _make_scope()
        facts = [_make_fact(scope, key=f"key_{i}") for i in range(3)]
        vectors = [[float(i)] * _EMBEDDING_DIM for i in range(3)]
        uc, repo, emb = _use_case(
            facts_by_id={f.id: f for f in facts},
            embedder=_mock_embedder(vectors),
        )
        await uc.execute(
            EmbedMemoryCommand(scope=scope, fact_ids=[f.id for f in facts])
        )
        # One call with all three content strings
        emb.embed_documents.assert_awaited_once()
        contents_arg = emb.embed_documents.call_args[0][0]
        assert len(contents_arg) == 3

    async def test_writes_each_vector_via_update_embedding(self) -> None:
        scope = _make_scope()
        facts = [_make_fact(scope, key=f"key_{i}") for i in range(2)]
        vectors = [[float(i)] * _EMBEDDING_DIM for i in range(2)]
        uc, repo, emb = _use_case(
            facts_by_id={f.id: f for f in facts},
            embedder=_mock_embedder(vectors),
        )
        await uc.execute(
            EmbedMemoryCommand(scope=scope, fact_ids=[f.id for f in facts])
        )
        assert repo.update_embedding.await_count == 2
        written_ids = {c.args[1] for c in repo.update_embedding.await_args_list}
        assert written_ids == {f.id for f in facts}

    async def test_result_counts_match(self) -> None:
        scope = _make_scope()
        present = [_make_fact(scope, key=f"k{i}") for i in range(3)]
        missing_id = uuid.uuid4()
        vectors = [[0.0] * _EMBEDDING_DIM for _ in present]
        uc, repo, _ = _use_case(
            facts_by_id={**{f.id: f for f in present}, missing_id: None},
            embedder=_mock_embedder(vectors),
        )
        result = await uc.execute(
            EmbedMemoryCommand(
                scope=scope, fact_ids=[f.id for f in present] + [missing_id]
            )
        )
        assert result.embedded == 3
        assert result.missing == 1
