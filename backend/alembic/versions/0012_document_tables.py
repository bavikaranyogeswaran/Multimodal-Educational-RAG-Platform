"""Add document_tables: a table on a page, with its columns named and rows aligned.

Parsing already records that a table exists and where it sits, joining every cell into
one string. That keeps the numbers out of the surrounding paragraphs but cannot answer a
question about them, because which column holds which measurement has been thrown away.
This table stores the grid instead.

Headers and units are arrays so a column can be searched for directly; rows are JSONB
because they are a nested rectangular grid, whose width is already guaranteed by the
entity that writes it.

Row-level security follows the direct pattern: the table carries user_id itself, so the
policy compares it to the authenticated user without a subquery.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_tables",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_element_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("headers", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("units", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("bounding_box_x0", sa.Float(), nullable=False),
        sa.Column("bounding_box_y0", sa.Float(), nullable=False),
        sa.Column("bounding_box_x1", sa.Float(), nullable=False),
        sa.Column("bounding_box_y1", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        # Cascades rather than nulls: without its element the table has no region on the
        # page, and a record that cannot be located can be neither cited nor highlighted.
        sa.ForeignKeyConstraint(
            ["source_element_id"], ["document_elements.id"], ondelete="CASCADE"
        ),
    )

    op.create_index("ix_document_tables_document_id", "document_tables", ["document_id"])
    op.create_index(
        "ix_document_tables_user_id_kb_id", "document_tables", ["user_id", "knowledge_base_id"]
    )
    op.create_index(
        "ix_document_tables_source_element_id", "document_tables", ["source_element_id"]
    )

    op.execute("ALTER TABLE document_tables ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_tables_user_isolation
        ON document_tables
        FOR ALL
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS document_tables_user_isolation ON document_tables")
    op.drop_index("ix_document_tables_source_element_id", table_name="document_tables")
    op.drop_index("ix_document_tables_user_id_kb_id", table_name="document_tables")
    op.drop_index("ix_document_tables_document_id", table_name="document_tables")
    op.drop_table("document_tables")
