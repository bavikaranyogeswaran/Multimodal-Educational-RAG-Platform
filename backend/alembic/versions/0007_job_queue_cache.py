from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(40), nullable=False),
        # Stored as the integer ordinal of JobPriority so ORDER BY priority DESC is native.
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        # Optional: allows jobs to be queued now and claimed only after a future time.
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        # Set only while the job is RUNNING; cleared on completion, failure, or cancellation.
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Supports FOR UPDATE SKIP LOCKED: status equality filter then priority DESC ordering.
    op.create_index("ix_processing_jobs_claim", "processing_jobs", ["status", "priority"])

    # UNLOGGED skips WAL — faster writes, contents discarded on crash.
    # That is the correct behaviour for a cache: a cold restart means cache misses,
    # not data loss. op.execute is used because CREATE UNLOGGED TABLE is not part of
    # the standard Alembic DDL vocabulary.
    op.execute(
        """
        CREATE UNLOGGED TABLE cache_entries (
            key        TEXT        PRIMARY KEY,
            value      BYTEA       NOT NULL,
            expires_at TIMESTAMPTZ
        )
        """
    )

    # Partial index used exclusively by the pg_cron sweep query below.
    # The WHERE clause restricts it to rows that can actually expire, so it stays
    # small even when many cache entries carry no TTL.
    op.execute(
        """
        CREATE INDEX ix_cache_entries_expires_at
        ON cache_entries (expires_at)
        WHERE expires_at IS NOT NULL
        """
    )

    # Sweep expired cache rows once per minute.
    # cron.schedule replaces any existing job of the same name, making this idempotent.
    op.execute(
        """
        SELECT cron.schedule(
            'sweep-expired-cache',
            '* * * * *',
            'DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at < now()'
        )
        """
    )


def downgrade() -> None:
    op.execute("SELECT cron.unschedule('sweep-expired-cache')")
    op.execute("DROP INDEX IF EXISTS ix_cache_entries_expires_at")
    op.execute("DROP TABLE IF EXISTS cache_entries")
    op.drop_index("ix_processing_jobs_claim", table_name="processing_jobs")
    op.drop_table("processing_jobs")
