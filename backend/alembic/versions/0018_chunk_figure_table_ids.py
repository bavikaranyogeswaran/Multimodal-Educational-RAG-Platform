"""Link each chunk directly to the figure or table it came from.

Standalone elements — figures, charts, diagrams, tables — each produce their own
chunk. A retrieval hit on one of those chunks lets the UI jump to the exact figure
or table row, and a citation can carry the image crop for a figure or the structured
data for a table without an extra join through `source_element_id`.

The columns are nullable foreign keys: only standalone-element chunks get a value,
and prose chunks that span several elements leave both NULL. Both point into
`document_figures` / `document_tables` with SET NULL on delete so a re-ingestion
that replaces those rows does not take the chunks with it.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column(
            "figure_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("document_figures.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "chunks",
        sa.Column(
            "table_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("document_tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chunks", "table_id")
    op.drop_column("chunks", "figure_id")
