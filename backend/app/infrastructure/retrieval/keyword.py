"""PostgreSQL full-text keyword retriever.

Searches the tsv tsvector column (populated by the chunks_tsv_update trigger)
using websearch_to_tsquery, ranked by ts_rank_cd. Only chunks from COMPLETED
documents are returned; the join to the documents table enforces this invariant,
matching the mandatory filter required by the retrieval spec.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.domain.enums import RetrieverKind
from app.domain.retrieval.entities import Evidence, EvidenceLabel, RetrievalFilters
from app.domain.scope import ScopeContext
from app.infrastructure.database.models.chunk import ChunkModel
from app.infrastructure.database.models.document import DocumentModel
from app.infrastructure.database.repositories.chunk import _to_entity
from app.infrastructure.database.repository import ScopedRepository

# Must match the text search configuration used by the chunks_tsv_update trigger.
_TS_CONFIG = "english"


class SqlKeywordRetriever(ScopedRepository):
    """Full-text search over chunk tsvectors using PostgreSQL RUM indexes.

    Uses websearch_to_tsquery so students can type natural queries with
    implicit AND; operators like OR and NOT are also recognised. Chunks from
    documents that are not COMPLETED are excluded by the document status join,
    so partially-ingested and deleting documents never appear in results.
    """

    async def search(
        self,
        scope: ScopeContext,
        query: str,
        *,
        top_k: int,
        filters: RetrievalFilters,
    ) -> Sequence[Evidence]:
        self._require_scope(scope)

        ts_query = func.websearch_to_tsquery(_TS_CONFIG, query)

        conditions = [
            self._scope_filter(ChunkModel),
            DocumentModel.status == "COMPLETED",
            ChunkModel.tsv.isnot(None),
            ChunkModel.tsv.op("@@")(ts_query),
            # Only the small chunks are searched. The trigger builds a tsvector for
            # every row it is given, so without this the larger passages they were cut
            # from would match too, returning the same content twice — once as the
            # paragraph, once as the section containing it.
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
            .order_by(func.ts_rank_cd(ChunkModel.tsv, ts_query).desc())
            .limit(top_k)
        )

        rows = (await self._session.execute(stmt)).scalars().all()

        return [
            Evidence(
                label=EvidenceLabel(rank + 1),
                chunk=_to_entity(row),
                retrievers=frozenset({RetrieverKind.KEYWORD}),
                rank=rank,
            )
            for rank, row in enumerate(rows)
        ]
