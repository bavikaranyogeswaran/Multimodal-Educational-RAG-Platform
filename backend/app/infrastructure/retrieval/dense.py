"""pgvector cosine-distance implementation of DenseRetriever."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.domain.enums import RetrieverKind
from app.domain.retrieval.entities import Evidence, EvidenceLabel, RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.chunk import ChunkModel
from app.infrastructure.database.models.document import DocumentModel
from app.infrastructure.database.repositories.chunk import _to_entity
from app.infrastructure.database.repository import ScopedRepository


class SqlDenseRetriever(ScopedRepository):
    """Cosine-distance nearest-neighbour search over chunk embeddings in pgvector.

    Chunks that have not yet been embedded (embedding IS NULL) are excluded so
    partially-processed documents never appear in results.
    """

    async def search(
        self,
        scope: ScopeContext,
        query_embedding: Sequence[float],
        *,
        top_k: int,
        filters: RetrievalFilters,
    ) -> Sequence[Evidence]:
        self._require_scope(scope)

        conditions = [
            self._scope_filter(ChunkModel),
            DocumentModel.status == "COMPLETED",
            ChunkModel.embedding.isnot(None),
            # Only the small chunks are searched. The larger passages they were cut
            # from are stored to be loaded around a hit, and matching them as well
            # would return the same content twice — once as the paragraph, once as
            # the section containing it — for two slots in the same ranking.
            ChunkModel.parent_chunk_id.isnot(None),
        ]

        if filters.document_ids:
            conditions.append(ChunkModel.document_id.in_(filters.document_ids))
        if filters.language:
            conditions.append(ChunkModel.language == filters.language)

        stmt = (
            select(ChunkModel)
            .join(DocumentModel, ChunkModel.document_id == DocumentModel.id)
            .where(*conditions)
            .order_by(ChunkModel.embedding.cosine_distance(list(query_embedding)))
            .limit(top_k)
        )

        rows = (await self._session.execute(stmt)).scalars().all()

        return [
            Evidence(
                label=EvidenceLabel(rank + 1),
                chunk=_to_entity(row),
                retrievers=frozenset({RetrieverKind.DENSE}),
                rank=rank,
            )
            for rank, row in enumerate(rows)
        ]
