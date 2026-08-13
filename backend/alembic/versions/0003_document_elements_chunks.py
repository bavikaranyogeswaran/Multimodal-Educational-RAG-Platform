from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "document_elements",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("element_type", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("processing_method", sa.String(20), nullable=False),
        sa.Column("bounding_box_x0", sa.Float(), nullable=True),
        sa.Column("bounding_box_y0", sa.Float(), nullable=True),
        sa.Column("bounding_box_x1", sa.Float(), nullable=True),
        sa.Column("bounding_box_y1", sa.Float(), nullable=True),
        sa.Column(
            "heading_path",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_elements_document_id", "document_elements", ["document_id"])
    op.create_index(
        "ix_document_elements_user_id_kb_id",
        "document_elements",
        ["user_id", "knowledge_base_id"],
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("parent_chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_element_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("chunk_type", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("chapter", sa.String(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column(
            "heading_path",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("element_type", sa.String(20), nullable=True),
        sa.Column("bounding_box_x0", sa.Float(), nullable=True),
        sa.Column("bounding_box_y0", sa.Float(), nullable=True),
        sa.Column("bounding_box_x1", sa.Float(), nullable=True),
        sa.Column("bounding_box_y1", sa.Float(), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model_id", sa.String(), nullable=True),
        sa.Column("embedding_dimension", sa.Integer(), nullable=True),
        sa.Column("embedding_version", sa.Integer(), nullable=True),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["chunks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_element_id"], ["document_elements.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_user_id_kb_id", "chunks", ["user_id", "knowledge_base_id"])
    op.create_index("ix_chunks_parent_chunk_id", "chunks", ["parent_chunk_id"])

    op.create_table(
        "chunk_elements",
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("element_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["element_id"], ["document_elements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id", "element_id"),
    )

    op.execute(
        """
        CREATE FUNCTION chunks_tsv_update() RETURNS trigger AS $$
        BEGIN
            new.tsv := to_tsvector('english', new.text);
            RETURN new;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER chunks_tsv_trigger
            BEFORE INSERT OR UPDATE OF text ON chunks
            FOR EACH ROW EXECUTE FUNCTION chunks_tsv_update()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS chunks_tsv_trigger ON chunks")
    op.execute("DROP FUNCTION IF EXISTS chunks_tsv_update()")
    op.drop_table("chunk_elements")
    op.drop_table("chunks")
    op.drop_table("document_elements")
