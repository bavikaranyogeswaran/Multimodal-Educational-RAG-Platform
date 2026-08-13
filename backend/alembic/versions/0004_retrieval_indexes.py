from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # HNSW builds a navigable small-world graph; m controls graph connectivity and
    # ef_construction controls how thoroughly the graph is searched during index build.
    # Higher ef_construction improves recall at the cost of a longer build time.
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 128)
        """
    )

    # RUM stores lexeme positions inside the index itself, so ts_rank_cd can score
    # results without touching the heap — GIN cannot do this.
    op.execute(
        """
        CREATE INDEX ix_chunks_tsv_rum
        ON chunks USING rum (tsv rum_tsvector_ops)
        """
    )

    op.create_index(
        "ix_chunks_scope_document_id",
        "chunks",
        ["user_id", "knowledge_base_id", "document_id"],
    )
    op.create_index(
        "ix_chunks_scope_chunk_type",
        "chunks",
        ["user_id", "knowledge_base_id", "chunk_type"],
    )
    op.create_index(
        "ix_chunks_scope_index_version",
        "chunks",
        ["user_id", "knowledge_base_id", "index_version"],
    )
    op.create_index(
        "ix_chunks_scope_language",
        "chunks",
        ["user_id", "knowledge_base_id", "language"],
    )
    op.create_index(
        "ix_chunks_scope_ordinal",
        "chunks",
        ["user_id", "knowledge_base_id", "ordinal"],
    )
    op.create_index(
        "ix_chunks_scope_content_hash",
        "chunks",
        ["user_id", "knowledge_base_id", "content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_scope_content_hash", table_name="chunks")
    op.drop_index("ix_chunks_scope_ordinal", table_name="chunks")
    op.drop_index("ix_chunks_scope_language", table_name="chunks")
    op.drop_index("ix_chunks_scope_index_version", table_name="chunks")
    op.drop_index("ix_chunks_scope_chunk_type", table_name="chunks")
    op.drop_index("ix_chunks_scope_document_id", table_name="chunks")
    op.execute("DROP INDEX IF EXISTS ix_chunks_tsv_rum")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
