from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class GraphEntityModel(Base):
    __tablename__ = "graph_entities"
    __table_args__ = (
        # Name lookup: find a node by canonical name within a scoped graph.
        Index("ix_graph_entities_scope_name", "user_id", "knowledge_base_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    entity_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # Source provenance — omitted for structural nodes (KNOWLEDGE_BASE, DOCUMENT).
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    # Tracks which extraction run produced this entity; analogous to chunks.index_version.
    graph_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GraphRelationshipModel(Base):
    """A directed, typed edge in the knowledge graph.

    Provenance columns (source_chunk_id, page_number, evidence) are NOT NULL at the
    schema level — the same invariant the domain entity enforces at the Python level.
    An edge without provenance is structurally impossible; the database constraint backs
    up what the type already refuses to allow.
    """

    __tablename__ = "graph_relationships"
    __table_args__ = (
        # Bidirectional traversal: one hop from a source, one hop to a target.
        Index("ix_graph_rels_source_entity_id", "source_entity_id"),
        Index("ix_graph_rels_target_entity_id", "target_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Denormalized scope so RLS and retrieval filters do not need to join graph_entities.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("graph_entities.id", ondelete="CASCADE"),
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("graph_entities.id", ondelete="CASCADE"),
    )
    relationship_type: Mapped[str] = mapped_column(String(30))
    # --- provenance: all three required; no defaults ---
    source_chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
    )
    page_number: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text)
    # ---------------------------------------------------
    weight: Mapped[float] = mapped_column(Float, server_default="1.0")
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    graph_version: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
