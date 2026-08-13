"""Enable Row-Level Security on every user-scoped table.

All policies follow the same isolation pattern: rows are visible and
modifiable only when the stored user_id matches the identity returned by
auth.uid(). Bridge tables (chunk_elements, conversation_retrieval_chunks)
have no user_id column so they delegate via an EXISTS subquery to their
nearest scoped parent.

System tables (processing_jobs, cache_entries) carry no user scope and are
left untouched here; they will be locked down alongside the service-role
policy when that phase lands.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── knowledge_bases ──────────────────────────────────────────────────────
    op.execute("ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY knowledge_bases_user_isolation ON knowledge_bases
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── documents ────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY documents_user_isolation ON documents
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── document_pages ───────────────────────────────────────────────────────
    op.execute("ALTER TABLE document_pages ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_pages_user_isolation ON document_pages
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── document_elements ────────────────────────────────────────────────────
    op.execute("ALTER TABLE document_elements ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY document_elements_user_isolation ON document_elements
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── chunks ───────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY chunks_user_isolation ON chunks
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── chunk_elements (bridge — delegates to chunks) ────────────────────────
    op.execute("ALTER TABLE chunk_elements ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY chunk_elements_user_isolation ON chunk_elements
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM chunks
                WHERE chunks.id = chunk_elements.chunk_id
                  AND chunks.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM chunks
                WHERE chunks.id = chunk_elements.chunk_id
                  AND chunks.user_id = auth.uid()
            )
        )
        """
    )

    # ── conversations ─────────────────────────────────────────────────────────
    op.execute("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY conversations_user_isolation ON conversations
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── messages ─────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY messages_user_isolation ON messages
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── conversation_retrieval_chunks (bridge — delegates to messages) ────────
    op.execute("ALTER TABLE conversation_retrieval_chunks ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY conversation_retrieval_chunks_user_isolation
        ON conversation_retrieval_chunks
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM messages
                WHERE messages.id = conversation_retrieval_chunks.message_id
                  AND messages.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM messages
                WHERE messages.id = conversation_retrieval_chunks.message_id
                  AND messages.user_id = auth.uid()
            )
        )
        """
    )

    # ── memory_facts ─────────────────────────────────────────────────────────
    op.execute("ALTER TABLE memory_facts ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY memory_facts_user_isolation ON memory_facts
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── graph_entities ───────────────────────────────────────────────────────
    op.execute("ALTER TABLE graph_entities ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY graph_entities_user_isolation ON graph_entities
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )

    # ── graph_relationships ───────────────────────────────────────────────────
    op.execute("ALTER TABLE graph_relationships ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY graph_relationships_user_isolation ON graph_relationships
        FOR ALL
        USING  (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid())
        """
    )


def downgrade() -> None:
    # Direct user_id tables — drop policy then disable RLS (reverse order of upgrade)
    for table in (
        "graph_relationships",
        "graph_entities",
        "memory_facts",
        "messages",
        "conversations",
        "chunks",
        "document_elements",
        "document_pages",
        "documents",
        "knowledge_bases",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_user_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Bridge tables
    op.execute(
        "DROP POLICY IF EXISTS conversation_retrieval_chunks_user_isolation "
        "ON conversation_retrieval_chunks"
    )
    op.execute("ALTER TABLE conversation_retrieval_chunks DISABLE ROW LEVEL SECURITY")

    op.execute(
        "DROP POLICY IF EXISTS chunk_elements_user_isolation ON chunk_elements"
    )
    op.execute("ALTER TABLE chunk_elements DISABLE ROW LEVEL SECURITY")
