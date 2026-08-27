"""Add dense embedding and full-text search support to memory_facts.

Two capabilities are added in one migration because they share a common purpose —
making facts retrievable by semantic similarity and keyword — and neither is useful
without the schema changes in 0019.

embedding vector(384)
  Stores the sentence-encoder output for the fact's content string. NULL until
  update_embedding() is called after the fact is written. HNSW index enables ANN
  search with cosine distance.

tsv tsvector
  Populated by a BEFORE INSERT OR UPDATE trigger from concat(key, ' ', value::text).
  RUM index (preferred over GIN) stores lexeme positions inline so ts_rank_cd can
  score results without heap access.

Revision ID: 0020
Revises: 0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_facts",
        sa.Column("embedding", sa.Text, nullable=True),
    )
    op.add_column(
        "memory_facts",
        sa.Column("tsv", sa.Text, nullable=True),
    )

    # Switch the embedding column to the real pgvector type.
    op.execute("ALTER TABLE memory_facts ALTER COLUMN embedding TYPE vector(384) USING NULL")

    # Switch the tsv column to tsvector.
    op.execute("ALTER TABLE memory_facts ALTER COLUMN tsv TYPE tsvector USING NULL")

    # Trigger function: concatenate key and value JSON text for indexing.
    op.execute(
        """
        CREATE FUNCTION memory_facts_tsv_update() RETURNS trigger AS $$
        BEGIN
            new.tsv := to_tsvector('english',
                coalesce(new.key, '') || ' ' || coalesce(new.value::text, ''));
            RETURN new;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_facts_tsv_trigger
            BEFORE INSERT OR UPDATE OF key, value ON memory_facts
            FOR EACH ROW EXECUTE FUNCTION memory_facts_tsv_update()
        """
    )

    # Back-fill tsv for any rows that pre-date the trigger.
    op.execute(
        """
        UPDATE memory_facts
        SET tsv = to_tsvector('english',
            coalesce(key, '') || ' ' || coalesce(value::text, ''))
        """
    )

    # HNSW index for ANN cosine-distance search over non-NULL embeddings.
    op.execute(
        """
        CREATE INDEX ix_memory_facts_embedding_hnsw
        ON memory_facts USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 128)
        WHERE embedding IS NOT NULL
        """
    )

    # RUM index stores lexeme positions so ts_rank_cd avoids heap access.
    op.execute(
        """
        CREATE INDEX ix_memory_facts_tsv_rum
        ON memory_facts USING rum (tsv rum_tsvector_ops)
        WHERE tsv IS NOT NULL
        """
    )

    # Composite index for the dense_search / keyword_search scope + status filter.
    op.create_index(
        "ix_memory_facts_scope_status_embedding",
        "memory_facts",
        ["user_id", "knowledge_base_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_facts_scope_status_embedding", table_name="memory_facts")
    op.execute("DROP INDEX IF EXISTS ix_memory_facts_tsv_rum")
    op.execute("DROP INDEX IF EXISTS ix_memory_facts_embedding_hnsw")
    op.execute("DROP TRIGGER IF EXISTS memory_facts_tsv_trigger ON memory_facts")
    op.execute("DROP FUNCTION IF EXISTS memory_facts_tsv_update()")
    op.drop_column("memory_facts", "tsv")
    op.drop_column("memory_facts", "embedding")
