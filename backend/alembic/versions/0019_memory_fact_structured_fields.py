"""Replace the free-text content column on memory_facts with structured fields.

FR-MEM-05 requires a fact to carry a semantic key, a structured value, and a confidence
score. FR-MEM-19 needs key as a first-class column for keyed lookup (exam dates,
identifiers) without a full-text scan. The old content string was a placeholder; no row
has ever been written by application code, so the column can be dropped cleanly.

New columns:
  key            — the semantic identifier, invariant across corrections
  value          — JSON payload (the actual fact content)
  confidence     — model certainty in [0.0, 1.0]
  source_message_id — the conversation message that triggered this fact, if known
  last_confirmed_at  — when the student last verified the fact is still correct
  expires_at         — optional system-controlled expiry for time-bounded facts

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("memory_facts", "content")
    op.add_column("memory_facts", sa.Column("key", sa.String(255), nullable=False, server_default=""))
    op.add_column("memory_facts", sa.Column("value", sa.JSON, nullable=False, server_default="{}"))
    op.add_column("memory_facts", sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"))
    op.add_column("memory_facts", sa.Column("source_message_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column("memory_facts", sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memory_facts", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    # Remove temporary server defaults — new rows are always written with real values.
    op.alter_column("memory_facts", "key", server_default=None)
    op.alter_column("memory_facts", "value", server_default=None)
    op.alter_column("memory_facts", "confidence", server_default=None)


def downgrade() -> None:
    op.drop_column("memory_facts", "expires_at")
    op.drop_column("memory_facts", "last_confirmed_at")
    op.drop_column("memory_facts", "source_message_id")
    op.drop_column("memory_facts", "confidence")
    op.drop_column("memory_facts", "value")
    op.drop_column("memory_facts", "key")
    op.add_column("memory_facts", sa.Column("content", sa.Text, nullable=False, server_default=""))
    op.alter_column("memory_facts", "content", server_default=None)
