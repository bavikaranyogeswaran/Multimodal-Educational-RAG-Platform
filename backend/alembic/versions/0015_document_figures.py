"""Add document_figures: figures, charts and diagrams detected on a page.

Parsing already records that a visual element exists and where it sits — as a
FIGURE, CHART or DIAGRAM element in document_elements — but nothing stores the
fields a student or the system would want: caption, number, axis labels, diagram
components, description. This table adds those fields.

All visual kinds share one table, discriminated by the `kind` column. Fields
specific to charts or diagrams are nullable because they do not exist at
detection time; they are filled in Phase 6.7 after OCR and model analysis.

Row-level security follows the same direct pattern as document_tables: the table
carries user_id, so the policy compares it to the authenticated user without a
subquery.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_figures",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_element_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("bounding_box_x0", sa.Float(), nullable=False),
        sa.Column("bounding_box_y0", sa.Float(), nullable=False),
        sa.Column("bounding_box_x1", sa.Float(), nullable=False),
        sa.Column("bounding_box_y1", sa.Float(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Populated in Phase 6.7.
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("surrounding_text", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # Chart-specific.
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("chart_type", sa.Text(), nullable=True),
        sa.Column("x_axis_label", sa.Text(), nullable=True),
        sa.Column("y_axis_label", sa.Text(), nullable=True),
        sa.Column("units_label", sa.Text(), nullable=True),
        sa.Column("legend", sa.Text(), nullable=True),
        sa.Column("data_labels", sa.Text(), nullable=True),
        sa.Column("visible_trend", sa.Text(), nullable=True),
        # Diagram-specific.
        sa.Column("diagram_labels", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("components", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("arrows", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("visible_relationships", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_element_id"], ["document_elements.id"], ondelete="CASCADE"
        ),
    )

    op.create_index("ix_document_figures_document_id", "document_figures", ["document_id"])
    op.create_index(
        "ix_document_figures_user_id_kb_id", "document_figures", ["user_id", "knowledge_base_id"]
    )
    op.create_index(
        "ix_document_figures_source_element_id", "document_figures", ["source_element_id"]
    )
    op.create_index(
        "ix_document_figures_scope_number",
        "document_figures",
        ["user_id", "knowledge_base_id", "number"],
    )

    op.execute("ALTER TABLE document_figures ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_figures_user_isolation
        ON document_figures
        FOR ALL
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS document_figures_user_isolation ON document_figures")
    op.drop_index("ix_document_figures_scope_number", table_name="document_figures")
    op.drop_index("ix_document_figures_source_element_id", table_name="document_figures")
    op.drop_index("ix_document_figures_user_id_kb_id", table_name="document_figures")
    op.drop_index("ix_document_figures_document_id", table_name="document_figures")
    op.drop_table("document_figures")
