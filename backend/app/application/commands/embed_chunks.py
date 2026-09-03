"""Use case: embed the searchable child chunks that ingestion wrote without vectors.

Called via a GENERATE_EMBEDDINGS job queued by the ingestion worker after save_batch
completes. Running embedding as its own job means the ingestion job completes as soon as
the document is parsed and chunked; the document becomes searchable once this job
finishes, which typically runs seconds later.

Chunk IDs are passed in the job payload rather than derived at runtime, so the job
embeds exactly the set that ingestion wrote — nothing more, nothing less.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import structlog

from app.domain.ports.adapters import EmbeddingPort
from app.domain.ports.repositories import ChunkRepository
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EmbedChunksCommand:
    scope: ScopeContext
    chunk_ids: tuple[UUID, ...]
    embedding_model_id: str
    index_version: int


@dataclass(frozen=True)
class EmbedChunksResult:
    embedded: int


class EmbedChunksUseCase:
    def __init__(self, chunk_repo: ChunkRepository, embedder: EmbeddingPort) -> None:
        self._chunk_repo = chunk_repo
        self._embedder = embedder

    async def execute(self, command: EmbedChunksCommand) -> EmbedChunksResult:
        scope = command.scope
        if not command.chunk_ids:
            return EmbedChunksResult(embedded=0)

        chunks = await self._chunk_repo.get_many(scope, list(command.chunk_ids))
        if not chunks:
            _log.warning(
                "embed_chunks.none_found",
                chunk_ids=[str(c) for c in command.chunk_ids],
            )
            return EmbedChunksResult(embedded=0)

        texts = [c.text.value for c in chunks]
        vectors = await self._embedder.embed_documents(texts)

        await self._chunk_repo.set_embeddings(
            scope,
            {c.id: v for c, v in zip(chunks, vectors, strict=True)},
            model_id=command.embedding_model_id,
            dimension=self._embedder.dimension,
            version=command.index_version,
        )

        _log.info(
            "embed_chunks.complete",
            embedded=len(chunks),
            model_id=command.embedding_model_id,
            index_version=command.index_version,
        )
        return EmbedChunksResult(embedded=len(chunks))
