"""Add model_invocations: one row per completed inference call.

Records provider, model, token counts, latency, fallback usage, and cache-hit status
as required by the observability specification. This is the persistence half of what
was previously a structlog-only event.

No row-level security: this is an internal observability table with no user_id.
Access via the service role key only; the authenticated API never exposes it.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        # Request correlation — the same trace ID that appears on every structlog line
        # for this request, allowing invocation rows to be joined with request logs.
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("task", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        # Null when the call came from the streaming path, where end-to-end latency
        # is not a single number.
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("used_fallback", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_invocations_trace_id", "model_invocations", ["trace_id"])
    op.create_index("ix_model_invocations_created_at", "model_invocations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_model_invocations_created_at", table_name="model_invocations")
    op.drop_index("ix_model_invocations_trace_id", table_name="model_invocations")
    op.drop_table("model_invocations")
