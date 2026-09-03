"""Unit tests for EmbedChunksUseCase."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.application.commands.embed_chunks import (
    EmbedChunksCommand,
    EmbedChunksResult,
    EmbedChunksUseCase,
)
from app.domain.enums import ChunkType, ElementType
from app.domain.documents.chunks import Chunk
from app.domain.scope import ScopeContext
from app.domain.values import UntrustedText

_SCOPE = ScopeContext(user_id=uuid.uuid4(), knowledge_base_id=uuid.uuid4())
_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
_MODEL_ID = "bge-small-en-v1.5"
_INDEX_VERSION = 1


def _chunk(text: str = "some text") -> Chunk:
    return Chunk(
        id=uuid.uuid4(),
        user_id=_SCOPE.user_id,
        knowledge_base_id=_SCOPE.knowledge_base_id,
        document_id=uuid.uuid4(),
        parent_chunk_id=uuid.uuid4(),
        chunk_type=ChunkType.TEXT,
        text=UntrustedText(text),
        token_count=len(text.split()),
        ordinal=0,
        page_start=1,
        page_end=1,
        index_version=_INDEX_VERSION,
        created_at=_NOW,
        element_type=ElementType.PARAGRAPH,
        content_hash="abc",
    )


def _setup(
    chunks: list[Chunk] | None = None,
) -> tuple[EmbedChunksUseCase, EmbedChunksCommand]:
    if chunks is None:
        chunks = [_chunk()]

    chunk_repo = AsyncMock()
    chunk_repo.get_many = AsyncMock(return_value=chunks)
    chunk_repo.set_embeddings = AsyncMock()

    embedder = AsyncMock()
    embedder.embed_documents = AsyncMock(
        side_effect=lambda texts: [[0.1] * 384 for _ in texts]
    )
    embedder.dimension = 384

    uc = EmbedChunksUseCase(chunk_repo=chunk_repo, embedder=embedder)
    cmd = EmbedChunksCommand(
        scope=_SCOPE,
        chunk_ids=tuple(c.id for c in chunks),
        embedding_model_id=_MODEL_ID,
        index_version=_INDEX_VERSION,
    )
    return uc, cmd


class TestHappyPath:
    async def test_returns_embedded_count(self) -> None:
        chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
        uc, cmd = _setup(chunks)
        result = await uc.execute(cmd)
        assert result.embedded == 3

    async def test_get_many_called_with_chunk_ids(self) -> None:
        chunks = [_chunk("hello"), _chunk("world")]
        uc, cmd = _setup(chunks)
        await uc.execute(cmd)
        uc._chunk_repo.get_many.assert_awaited_once_with(_SCOPE, list(cmd.chunk_ids))

    async def test_embed_documents_called_with_chunk_texts(self) -> None:
        chunks = [_chunk("hello world")]
        uc, cmd = _setup(chunks)
        await uc.execute(cmd)
        uc._embedder.embed_documents.assert_awaited_once()
        texts = uc._embedder.embed_documents.call_args.args[0]
        assert texts == ["hello world"]

    async def test_set_embeddings_called_with_model_metadata(self) -> None:
        chunks = [_chunk()]
        uc, cmd = _setup(chunks)
        await uc.execute(cmd)
        uc._chunk_repo.set_embeddings.assert_awaited_once()
        kw = uc._chunk_repo.set_embeddings.call_args.kwargs
        assert kw["model_id"] == _MODEL_ID
        assert kw["dimension"] == 384
        assert kw["version"] == _INDEX_VERSION

    async def test_set_embeddings_maps_chunk_ids_to_vectors(self) -> None:
        chunk = _chunk("text")
        uc, cmd = _setup([chunk])
        await uc.execute(cmd)
        mapping = uc._chunk_repo.set_embeddings.call_args.args[1]
        assert chunk.id in mapping
        assert len(mapping[chunk.id]) == 384

    async def test_multiple_chunks_produce_correct_mapping(self) -> None:
        chunks = [_chunk(f"text {i}") for i in range(3)]
        uc, cmd = _setup(chunks)
        await uc.execute(cmd)
        mapping = uc._chunk_repo.set_embeddings.call_args.args[1]
        assert set(mapping.keys()) == {c.id for c in chunks}


class TestNoOps:
    async def test_empty_chunk_ids_returns_zero(self) -> None:
        uc, _ = _setup([])
        cmd = EmbedChunksCommand(
            scope=_SCOPE,
            chunk_ids=(),
            embedding_model_id=_MODEL_ID,
            index_version=_INDEX_VERSION,
        )
        result = await uc.execute(cmd)
        assert result == EmbedChunksResult(embedded=0)
        uc._chunk_repo.get_many.assert_not_awaited()

    async def test_no_chunks_found_returns_zero(self) -> None:
        chunk_repo = AsyncMock()
        chunk_repo.get_many = AsyncMock(return_value=[])
        chunk_repo.set_embeddings = AsyncMock()
        embedder = AsyncMock()
        uc = EmbedChunksUseCase(chunk_repo=chunk_repo, embedder=embedder)
        cmd = EmbedChunksCommand(
            scope=_SCOPE,
            chunk_ids=(uuid.uuid4(),),
            embedding_model_id=_MODEL_ID,
            index_version=_INDEX_VERSION,
        )
        result = await uc.execute(cmd)
        assert result.embedded == 0
        embedder.embed_documents.assert_not_awaited()
        chunk_repo.set_embeddings.assert_not_awaited()
