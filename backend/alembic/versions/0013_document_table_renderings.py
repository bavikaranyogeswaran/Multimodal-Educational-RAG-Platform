"""Add the serialised forms of a table to document_tables.

Four readers, four forms. JSON is what a caller rebuilds the grid from, Markdown is what
goes in front of a model, HTML is for a viewer that lays it out, and the prose form is
what gets embedded.

Stored rather than derived on demand. The prose form is the text a vector is built from,
and a vector only means anything against the exact text that produced it — re-rendering
later with a changed renderer would leave stored vectors describing text that no longer
exists anywhere.

Every column is nullable: tables written before this migration have no renderings, and
backfilling them is a reprocessing concern rather than a schema one.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_tables", sa.Column("table_json", sa.Text(), nullable=True))
    op.add_column("document_tables", sa.Column("markdown", sa.Text(), nullable=True))
    op.add_column("document_tables", sa.Column("html", sa.Text(), nullable=True))
    op.add_column("document_tables", sa.Column("embedding_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_tables", "embedding_text")
    op.drop_column("document_tables", "html")
    op.drop_column("document_tables", "markdown")
    op.drop_column("document_tables", "table_json")
