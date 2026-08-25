from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class ConversationModel(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_id_kb_id", "user_id", "knowledge_base_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
    )
    title: Mapped[str] = mapped_column(Text)
    active_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
    )
    active_page_number: Mapped[int | None] = mapped_column(Integer)
    # Figure and table IDs reference visual elements defined in a later phase; no FK yet.
    active_figure_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    active_table_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True))
    # Replaced wholesale by the compaction job; never appended to.
    rolling_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageModel(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
    )
    # Denormalized from the conversation so RLS and retrieval filters work without a join.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    role: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    # Model metadata is NULL on user messages and populated after generation on assistant messages.
    model_id: Mapped[str | None] = mapped_column(String)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(String(50))
    # Which prompt template produced this answer, so answers written under different
    # prompts stay distinguishable when their quality is compared.
    prompt_version: Mapped[str | None] = mapped_column(String(64))


class ConversationRetrievalChunkModel(Base):
    """Records which chunks were retrieved for a message and their post-reranking position.

    The composite primary key (message_id, chunk_id) prevents duplicates.
    created_at is included so this table can be range-partitioned by time if row volume
    justifies it — no partitions are created at this phase.
    """

    __tablename__ = "conversation_retrieval_chunks"
    __table_args__ = (
        Index("ix_conv_ret_chunks_message_id", "message_id"),
        Index("ix_conv_ret_chunks_chunk_id", "chunk_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageCitationModel(Base):
    """Which passage each claim in an answer rested on, recorded when the answer was given.

    Location and type are copied here rather than read through `chunk_id` at display time,
    for the same reason the hash is stored: reprocessing rewrites chunks, and a citation
    that resolved against the current text would quietly start describing a passage the
    answer never saw. The columns hold what was true when the claim was made.

    The composite primary key (message_id, citation_order) both prevents duplicates and
    fixes the order the answer argues in, so the set reads back in the sequence it was
    written without a sort column beside it.
    """

    __tablename__ = "message_citations"
    __table_args__ = (
        Index("ix_message_citations_message_id", "message_id"),
        Index("ix_message_citations_chunk_id", "chunk_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    citation_order: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The positional label the model actually cited, stored unbracketed. Meaningless
    # outside the answer that issued it, and kept for exactly that reason: it is how the
    # stored record lines up with the text of the answer.
    label: Mapped[str] = mapped_column(String(16))
    # SET NULL rather than CASCADE, for the same reason the columns below are copies
    # rather than lookups: reprocessing deletes every chunk of a document and writes new
    # ones, and under CASCADE that silently erased the sources of every answer already
    # given about it. Null here means the passage this rested on is no longer stored, not
    # that the claim was never attributed — where to look is still recorded beside it.
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
    )
    chunk_type: Mapped[str] = mapped_column(String(20))
    element_type: Mapped[str | None] = mapped_column(String(20))
    page_number: Mapped[int] = mapped_column(Integer)
    bounding_box_x0: Mapped[float | None] = mapped_column(Float)
    bounding_box_y0: Mapped[float | None] = mapped_column(Float)
    bounding_box_x1: Mapped[float | None] = mapped_column(Float)
    bounding_box_y1: Mapped[float | None] = mapped_column(Float)
    # What the passage said when it was cited. A row whose hash no longer matches its
    # chunk is pointing at text that has since been rewritten.
    evidence_hash: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryFactModel(Base):
    __tablename__ = "memory_facts"
    __table_args__ = (
        Index("ix_memory_facts_user_id_kb_id", "user_id", "knowledge_base_id"),
        # Retrieval always filters on status; scope + status together avoid a full table scan.
        Index("ix_memory_facts_scope_status", "user_id", "knowledge_base_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True))
    memory_type: Mapped[str] = mapped_column(String(30))
    content: Mapped[str] = mapped_column(Text)
    # Stored as the integer ordinal of the MemoryProvenance IntEnum so that ordering
    # (USER_CORRECTION > APPLICATION_EVENT > USER_STATEMENT > ASSISTANT_INFERENCE) is
    # native to the column and sortable without a lookup table.
    provenance: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Self-referential: names the fact that replaced this one when it was superseded.
    # SET NULL rather than CASCADE so the audit chain survives if a successor is deleted.
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("memory_facts.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
