"""SQLAlchemy implementation of ChunkRepository."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.domain.documents.chunks import Chunk
from app.domain.enums import ChunkType, ElementType
from app.domain.scope import ScopeContext
from app.domain.values import BoundingBox, HeadingPath, UntrustedText
from app.infrastructure.database.models.chunk import ChunkModel
from app.infrastructure.database.repository import ScopedRepository


class SqlChunkRepository(ScopedRepository):
    """Reads and writes Chunk aggregates via SQLAlchemy."""

    async def get(self, scope: ScopeContext, chunk_id: UUID) -> Chunk | None:
        self._require_scope(scope)
        stmt = (
            select(ChunkModel)
            .where(
                ChunkModel.id == chunk_id,
                self._scope_filter(ChunkModel),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_entity(row) if row else None

    async def save_batch(
        self, scope: ScopeContext, chunks: Sequence[Chunk]
    ) -> None:
        self._require_scope(scope)
        for chunk in chunks:
            await self._session.merge(_to_model(chunk))

    async def list_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> Sequence[Chunk]:
        self._require_scope(scope)
        stmt = (
            select(ChunkModel)
            .where(
                ChunkModel.document_id == document_id,
                self._scope_filter(ChunkModel),
            )
            # Parents first, then the children, because the two tiers are numbered
            # separately — ordering on the number alone would interleave a section
            # with an unrelated paragraph that happens to share its position.
            .order_by(
                ChunkModel.parent_chunk_id.is_(None).desc(),
                ChunkModel.ordinal.asc(),
            )
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_entity(row) for row in rows]

    async def delete_for_document(
        self, scope: ScopeContext, document_id: UUID
    ) -> None:
        self._require_scope(scope)
        stmt = sa_delete(ChunkModel).where(
            ChunkModel.document_id == document_id,
            self._scope_filter(ChunkModel),
        )
        await self._session.execute(stmt)

    async def set_embeddings(
        self,
        scope: ScopeContext,
        embeddings: Mapping[UUID, Sequence[float]],
        *,
        model_id: str,
        dimension: int,
        version: int,
    ) -> None:
        self._require_scope(scope)
        for chunk_id, vector in embeddings.items():
            stmt = (
                sa.update(ChunkModel)
                .where(
                    ChunkModel.id == chunk_id,
                    self._scope_filter(ChunkModel),
                )
                .values(
                    embedding=list(vector),
                    embedding_model_id=model_id,
                    embedding_dimension=dimension,
                    embedding_version=version,
                )
            )
            await self._session.execute(stmt)


def _utc(dt: datetime) -> datetime:
    """Return dt unchanged if timezone-aware; attach UTC when SQLite strips it."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _to_entity(row: ChunkModel) -> Chunk:
    bbox = None
    if row.bounding_box_x0 is not None:
        bbox = BoundingBox(
            x0=row.bounding_box_x0,
            y0=row.bounding_box_y0,  # type: ignore[arg-type]
            x1=row.bounding_box_x1,  # type: ignore[arg-type]
            y1=row.bounding_box_y1,  # type: ignore[arg-type]
        )
    raw_path = row.heading_path
    segments: tuple[str, ...] = tuple(raw_path) if raw_path else ()
    element_type = ElementType(row.element_type) if row.element_type else None
    return Chunk(
        id=row.id,
        user_id=row.user_id,
        knowledge_base_id=row.knowledge_base_id,
        document_id=row.document_id,
        chunk_type=ChunkType(row.chunk_type),
        text=UntrustedText(row.text),
        token_count=row.token_count,
        ordinal=row.ordinal,
        page_start=row.page_start,
        page_end=row.page_end,
        index_version=row.index_version,
        created_at=_utc(row.created_at),
        parent_chunk_id=row.parent_chunk_id,
        source_element_id=row.source_element_id,
        chapter=row.chapter,
        section=row.section,
        heading_path=HeadingPath(segments),
        element_type=element_type,
        bounding_box=bbox,
        language=row.language,
        content_hash=row.content_hash,
    )


def _to_model(chunk: Chunk) -> ChunkModel:
    bbox = chunk.bounding_box
    return ChunkModel(
        id=chunk.id,
        user_id=chunk.user_id,
        knowledge_base_id=chunk.knowledge_base_id,
        document_id=chunk.document_id,
        parent_chunk_id=chunk.parent_chunk_id,
        source_element_id=chunk.source_element_id,
        chunk_type=chunk.chunk_type.value,
        text=chunk.text.value,
        token_count=chunk.token_count,
        ordinal=chunk.ordinal,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        chapter=chunk.chapter,
        section=chunk.section,
        heading_path=list(chunk.heading_path.segments),
        element_type=chunk.element_type.value if chunk.element_type else None,
        bounding_box_x0=bbox.x0 if bbox else None,
        bounding_box_y0=bbox.y0 if bbox else None,
        bounding_box_x1=bbox.x1 if bbox else None,
        bounding_box_y1=bbox.y1 if bbox else None,
        language=chunk.language,
        content_hash=chunk.content_hash,
        index_version=chunk.index_version,
        created_at=chunk.created_at,
        # embedding, embedding_model_id, embedding_dimension, embedding_version, tsv
        # are populated by the embedding worker after ingestion — not set here.
    )
