"""Add conversation_summaries table for hierarchical episode summaries.

Each row is an immutable snapshot of a message block written after the
compaction threshold is crossed. The embedding column is NULL on insert and
populated by a separate worker step; the HNSW index is partial so it only
covers rows that already have a vector.

Revision ID: 0021
Revises: 0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "knowledge_base_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("message_count", sa.Integer, nullable=False),
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index(
        "ix_conv_summaries_user_kb",
        "conversation_summaries",
        ["user_id", "knowledge_base_id"],
    )
    op.create_index(
        "ix_conv_summaries_conv_id",
        "conversation_summaries",
        ["conversation_id"],
    )

    # Switch embedding column from text placeholder to real pgvector type.
    op.execute(
        "ALTER TABLE conversation_summaries"
        " ALTER COLUMN embedding TYPE vector(384) USING NULL"
    )

    # Partial HNSW index — cosine ANN over rows that already have embeddings.
    op.execute(
        """
        CREATE INDEX ix_conv_summaries_embedding_hnsw
        ON conversation_summaries USING hnsw(embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conv_summaries_embedding_hnsw")
    op.drop_index("ix_conv_summaries_conv_id", table_name="conversation_summaries")
    op.drop_index("ix_conv_summaries_user_kb", table_name="conversation_summaries")
    op.drop_table("conversation_summaries")
