from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_entities",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Provenance for content-derived nodes; omitted for structural nodes.
        sa.Column("source_document_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("source_chunk_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        # Tracks which extraction run produced this entity; analogous to chunks.index_version.
        sa.Column("graph_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk_id"], ["chunks.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_graph_entities_scope_name",
        "graph_entities",
        ["user_id", "knowledge_base_id", "name"],
    )

    op.create_table(
        "graph_relationships",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        # Denormalized scope so RLS policies and retrieval filters work without joining graph_entities.
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(30), nullable=False),
        # Provenance columns: all three are NOT NULL.
        # The domain entity enforces this at the Python level; the schema backs it up at the
        # database level so the constraint cannot be bypassed by raw SQL writes.
        sa.Column("source_chunk_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("graph_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_entity_id"], ["graph_entities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"], ["graph_entities.id"], ondelete="CASCADE"
        ),
        # Deleting the source chunk removes the edge's provenance — the edge goes with it.
        sa.ForeignKeyConstraint(
            ["source_chunk_id"], ["chunks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_graph_rels_source_entity_id", "graph_relationships", ["source_entity_id"]
    )
    op.create_index(
        "ix_graph_rels_target_entity_id", "graph_relationships", ["target_entity_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_graph_rels_target_entity_id", table_name="graph_relationships")
    op.drop_index("ix_graph_rels_source_entity_id", table_name="graph_relationships")
    op.drop_table("graph_relationships")
    op.drop_index("ix_graph_entities_scope_name", table_name="graph_entities")
    op.drop_table("graph_entities")
