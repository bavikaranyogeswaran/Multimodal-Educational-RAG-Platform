from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("active_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("active_page_number", sa.Integer(), nullable=True),
        # No FK constraints for figure/table IDs; those tables are defined in a later phase.
        sa.Column("active_figure_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("active_table_id", sa.Uuid(as_uuid=True), nullable=True),
        # Replaced wholesale by the compaction job; never appended to in place.
        sa.Column("rolling_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["active_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_user_id_kb_id", "conversations", ["user_id", "knowledge_base_id"]
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=True), nullable=False),
        # Denormalized copies of the conversation scope so RLS policies and retrieval
        # queries work without joining back to conversations on every read.
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        # Model metadata is NULL on user messages and filled in after generation.
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(50), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "conversation_retrieval_chunks",
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        # Present so this table can be converted to PARTITION BY RANGE(created_at) later
        # without a DDL change — no partitions are created at this phase.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "chunk_id"),
    )
    op.create_index(
        "ix_conv_ret_chunks_message_id", "conversation_retrieval_chunks", ["message_id"]
    )
    op.create_index(
        "ix_conv_ret_chunks_chunk_id", "conversation_retrieval_chunks", ["chunk_id"]
    )

    op.create_table(
        "memory_facts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("memory_type", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Stored as the integer ordinal of MemoryProvenance so the ordering it implies
        # (higher = more trusted) is native to the column and sortable without a lookup.
        sa.Column("provenance", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        # Self-referential FK: names the fact that superseded this one.
        # SET NULL rather than CASCADE so the audit chain survives if a successor is later deleted.
        sa.Column("superseded_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["superseded_by"], ["memory_facts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_facts_user_id_kb_id", "memory_facts", ["user_id", "knowledge_base_id"]
    )
    op.create_index(
        "ix_memory_facts_scope_status",
        "memory_facts",
        ["user_id", "knowledge_base_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_facts_scope_status", table_name="memory_facts")
    op.drop_index("ix_memory_facts_user_id_kb_id", table_name="memory_facts")
    op.drop_table("memory_facts")
    op.drop_index("ix_conv_ret_chunks_chunk_id", table_name="conversation_retrieval_chunks")
    op.drop_index("ix_conv_ret_chunks_message_id", table_name="conversation_retrieval_chunks")
    op.drop_table("conversation_retrieval_chunks")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_id_kb_id", table_name="conversations")
    op.drop_table("conversations")
