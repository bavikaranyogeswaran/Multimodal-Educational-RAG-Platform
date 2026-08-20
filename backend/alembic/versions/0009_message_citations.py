"""Add message_citations: the passage behind each claim, recorded at answer time.

Location, type and content hash are stored on the row rather than read through chunk_id
when a citation is displayed. Reprocessing rewrites chunks, and a citation resolved
against current text would silently begin describing a passage the answer never saw.

Row-level security follows the bridge-table pattern established in 0008: the table has no
user_id of its own, so it delegates to the message it hangs off via an EXISTS subquery.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_citations",
        sa.Column("message_id", sa.Uuid(as_uuid=True), nullable=False),
        # Part of the primary key, so the order the answer argues in is fixed by the key
        # itself rather than by a sort column that could disagree with it.
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(16), nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        # Copied from the chunk at citation time, not joined at read time — see the
        # module docstring.
        sa.Column("chunk_type", sa.String(20), nullable=False),
        sa.Column("element_type", sa.String(20), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bounding_box_x0", sa.Float(), nullable=True),
        sa.Column("bounding_box_y0", sa.Float(), nullable=True),
        sa.Column("bounding_box_x1", sa.Float(), nullable=True),
        sa.Column("bounding_box_y1", sa.Float(), nullable=True),
        sa.Column("evidence_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "citation_order"),
    )
    op.create_index("ix_message_citations_message_id", "message_citations", ["message_id"])
    op.create_index("ix_message_citations_chunk_id", "message_citations", ["chunk_id"])

    # ── Row-level security (bridge — delegates to messages, as in 0008) ───────
    op.execute("ALTER TABLE message_citations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY message_citations_user_isolation
        ON message_citations
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM messages
                WHERE messages.id = message_citations.message_id
                  AND messages.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM messages
                WHERE messages.id = message_citations.message_id
                  AND messages.user_id = auth.uid()
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS message_citations_user_isolation ON message_citations")
    op.drop_index("ix_message_citations_chunk_id", table_name="message_citations")
    op.drop_index("ix_message_citations_message_id", table_name="message_citations")
    op.drop_table("message_citations")
