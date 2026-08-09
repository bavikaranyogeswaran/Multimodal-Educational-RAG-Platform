"""Activate PostgreSQL extensions required for the schema.

vector  — pgvector column type and HNSW / IVFFlat indexes for dense retrieval
rum     — RUM full-text index for BM25-style keyword retrieval
pg_cron — scheduled sweep of expired cache_entries rows
pg_trgm — trigram similarity used by pg_trgm GIN indexes

Revision ID: 0001
Revises:
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS rum")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # Extensions are intentionally not dropped on downgrade. Removing them while
    # subsequent migrations' vector columns, rum indexes, and cron jobs still
    # reference them would cascade-drop those objects. Each migration that creates
    # extension-dependent objects cleans up its own objects on downgrade; the
    # extensions themselves remain until the database is torn down entirely.
    pass
