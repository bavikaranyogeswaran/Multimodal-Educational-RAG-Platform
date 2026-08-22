"""Add the number a document gave a table, so it can be referenced and selected.

A textbook names its tables — "Table 4.2" — and students refer to them that way. The
number lived only inside the caption sentence, where nothing but a substring search
could reach it. Storing it as its own column is what lets a question naming a table
resolve to that table, and what lets a claim citing a table number be checked against
the tables that were actually supplied.

Indexed by scope alongside the number, because looking one up is a scoped lookup by
number and that is the access path this column exists to serve.

Nullable: plenty of tables are printed without a number at all.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("document_tables", sa.Column("number", sa.Text(), nullable=True))
    op.create_index(
        "ix_document_tables_scope_number",
        "document_tables",
        ["user_id", "knowledge_base_id", "number"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_tables_scope_number", table_name="document_tables")
    op.drop_column("document_tables", "number")
