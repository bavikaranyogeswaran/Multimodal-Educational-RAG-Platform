from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("learning_goal", sa.Text(), nullable=True),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column(
            "explanation_level", sa.String(20), nullable=False, server_default="INTERMEDIATE"
        ),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("graph_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("active_index_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_graph_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_user_id", "knowledge_bases", ["user_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_user_id_kb_id", "documents", ["user_id", "knowledge_base_id"])

    op.create_table(
        "document_pages",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("rotation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])
    op.create_index(
        "ix_document_pages_user_id_kb_id", "document_pages", ["user_id", "knowledge_base_id"]
    )


def downgrade() -> None:
    op.drop_table("document_pages")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
