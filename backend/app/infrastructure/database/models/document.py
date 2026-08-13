from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class DocumentModel(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_user_id_kb_id", "user_id", "knowledge_base_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(20), server_default="PENDING")
    title: Mapped[str | None] = mapped_column(String)
    page_count: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(10), server_default="en")
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPageModel(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        Index("ix_document_pages_document_id", "document_id"),
        Index("ix_document_pages_user_id_kb_id", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    page_number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    rotation: Mapped[int] = mapped_column(Integer, server_default="0")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
