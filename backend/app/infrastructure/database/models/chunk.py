from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base

_EMBEDDING_DIM = 384


class DocumentElementModel(Base):
    __tablename__ = "document_elements"
    __table_args__ = (
        Index("ix_document_elements_document_id", "document_id"),
        Index("ix_document_elements_user_id_kb_id", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    page_number: Mapped[int] = mapped_column(Integer)
    element_type: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    reading_order: Mapped[int] = mapped_column(Integer)
    processing_method: Mapped[str] = mapped_column(String(20))
    bounding_box_x0: Mapped[float | None] = mapped_column(Float)
    bounding_box_y0: Mapped[float | None] = mapped_column(Float)
    bounding_box_x1: Mapped[float | None] = mapped_column(Float)
    bounding_box_y1: Mapped[float | None] = mapped_column(Float)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text()), server_default=sa.text("'{}'"))
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChunkModel(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_user_id_kb_id", "user_id", "knowledge_base_id"),
        Index("ix_chunks_parent_chunk_id", "parent_chunk_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    # Self-referential: child chunks name their parent; parent chunks omit this.
    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
    )
    # Primary element whose text was used to build this chunk (optional provenance shortcut).
    source_element_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_elements.id", ondelete="SET NULL"),
    )
    chunk_type: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    chapter: Mapped[str | None] = mapped_column(String)
    section: Mapped[str | None] = mapped_column(String)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text()), server_default=sa.text("'{}'"))
    element_type: Mapped[str | None] = mapped_column(String(20))
    bounding_box_x0: Mapped[float | None] = mapped_column(Float)
    bounding_box_y0: Mapped[float | None] = mapped_column(Float)
    bounding_box_x1: Mapped[float | None] = mapped_column(Float)
    bounding_box_y1: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str] = mapped_column(String(10), server_default="en")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    # Populated asynchronously after ingestion; NULL until the embedding worker runs.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBEDDING_DIM))
    embedding_model_id: Mapped[str | None] = mapped_column(String)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    embedding_version: Mapped[int | None] = mapped_column(Integer)
    # Tracks which embedding index this chunk was built for.
    index_version: Mapped[int] = mapped_column(Integer, server_default="1")
    # Maintained by the chunks_tsv_update trigger; never written directly from Python.
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChunkElementModel(Base):
    """Join table recording which document elements contributed to each chunk.

    The composite primary key enforces uniqueness; no additional columns are
    needed since element order is captured by DocumentElementModel.reading_order.
    """

    __tablename__ = "chunk_elements"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    element_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("document_elements.id", ondelete="CASCADE"),
        primary_key=True,
    )
