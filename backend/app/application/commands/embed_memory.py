"""Use case: compute and store dense embeddings for a batch of memory facts.

Typically called immediately after ExtractMemoryUseCase using the fact IDs
from ExtractMemoryResult.embeddable_ids. Can also be called standalone to
re-embed facts whose content has changed, or to backfill facts written before
the embedding model was configured.

Facts are loaded in a single pass. Any ID that resolves to None (deleted or
never written) is counted as missing and skipped without raising. The remaining
facts' content strings are batched into one embedding call, then each vector is
written back via update_embedding(). One embedding call per execute() is
deliberate — the embedding model is on a GPU and batching across facts keeps
the round-trip count low.
"""

from __future__ import annotations

import structlog
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.domain.ports.adapters import EmbeddingPort
from app.domain.ports.repositories import MemoryRepository
from app.domain.scope import ScopeContext

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EmbedMemoryCommand:
    scope: ScopeContext
    fact_ids: Sequence[UUID]


@dataclass(frozen=True)
class EmbedMemoryResult:
    embedded: int
    missing: int


class EmbedMemoryUseCase:
    """Embed a batch of memory facts and write the vectors back to the repository.

    The caller provides the scope and the IDs of facts that need a vector.
    Facts that are not found are silently skipped — a deleted fact between
    extraction and embedding is not an error.
    """

    def __init__(
        self,
        memory_repo: MemoryRepository,
        embedder: EmbeddingPort,
    ) -> None:
        self._memory_repo = memory_repo
        self._embedder = embedder

    async def execute(self, command: EmbedMemoryCommand) -> EmbedMemoryResult:
        scope = command.scope

        if not command.fact_ids:
            return EmbedMemoryResult(embedded=0, missing=0)

        # Load all facts first so the embed call is one round-trip.
        loaded = []
        missing = 0
        for fact_id in command.fact_ids:
            fact = await self._memory_repo.get(scope, fact_id)
            if fact is None:
                _log.debug(
                    "embed_memory.fact_not_found",
                    fact_id=str(fact_id),
                )
                missing += 1
                continue
            loaded.append(fact)

        if not loaded:
            return EmbedMemoryResult(embedded=0, missing=missing)

        contents = [f.content for f in loaded]
        vectors = await self._embedder.embed_documents(contents)

        for fact, vector in zip(loaded, vectors, strict=True):
            await self._memory_repo.update_embedding(scope, fact.id, vector)

        _log.info(
            "embed_memory.complete",
            embedded=len(loaded),
            missing=missing,
        )

        return EmbedMemoryResult(embedded=len(loaded), missing=missing)
