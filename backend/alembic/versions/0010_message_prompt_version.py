"""Add messages.prompt_version: which prompt template produced an answer.

Nullable, and stays null on user messages — a question is not produced by a prompt — and
on answers written before this column existed. Backfilling would mean asserting which
template produced them, which nobody recorded and nobody can now recover.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("prompt_version", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "prompt_version")
