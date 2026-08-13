"""Unit tests for migration 0006 and graph ORM models.

Runs without a live database. Migration tests inspect source for expected table
and column definitions. Model tests use SQLAlchemy's table introspection API.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_MIGRATION_FILE = "0006_graph_entities_relationships.py"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGraphMigration:
    def test_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.revision == "0006"

    def test_down_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.down_revision == "0005"

    def test_upgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).upgrade)

    def test_downgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).downgrade)

    def test_upgrade_creates_graph_entities_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"graph_entities"' in src

    def test_upgrade_creates_graph_relationships_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"graph_relationships"' in src

    def test_graph_relationships_provenance_columns_present(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "source_chunk_id" in src
        assert "page_number" in src
        assert "evidence" in src

    def test_graph_entities_has_graph_version(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "graph_version" in src

    def test_graph_entities_scope_name_index(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "ix_graph_entities_scope_name" in src

    def test_bidirectional_traversal_indexes(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "ix_graph_rels_source_entity_id" in src
        assert "ix_graph_rels_target_entity_id" in src

    def test_downgrade_drops_both_tables(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "graph_relationships" in src
        assert "graph_entities" in src


class TestGraphEntityModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        assert GraphEntityModel.__tablename__ == "graph_entities"

    def test_has_scope_columns(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        cols = {c.name for c in GraphEntityModel.__table__.columns}
        assert "user_id" in cols
        assert "knowledge_base_id" in cols

    def test_name_is_not_nullable(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        col = GraphEntityModel.__table__.c["name"]
        assert not col.nullable

    def test_entity_type_is_not_nullable(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        col = GraphEntityModel.__table__.c["entity_type"]
        assert not col.nullable

    def test_source_fields_are_nullable(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        for name in ("description", "source_document_id", "source_chunk_id", "page_number"):
            col = GraphEntityModel.__table__.c[name]
            assert col.nullable, f"{name} should be nullable"

    def test_graph_version_has_server_default(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        col = GraphEntityModel.__table__.c["graph_version"]
        assert col.server_default is not None

    def test_knowledge_base_id_has_fk_to_knowledge_bases(self) -> None:
        from app.infrastructure.database.models.graph import GraphEntityModel

        fks = GraphEntityModel.__table__.c["knowledge_base_id"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "knowledge_bases.id" in targets


class TestGraphRelationshipModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        assert GraphRelationshipModel.__tablename__ == "graph_relationships"

    def test_has_scope_columns(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        cols = {c.name for c in GraphRelationshipModel.__table__.columns}
        assert "user_id" in cols
        assert "knowledge_base_id" in cols

    def test_provenance_columns_are_not_nullable(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        for name in ("source_chunk_id", "page_number", "evidence"):
            col = GraphRelationshipModel.__table__.c[name]
            assert not col.nullable, f"{name} must be NOT NULL (provenance invariant)"

    def test_extraction_confidence_is_nullable(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        col = GraphRelationshipModel.__table__.c["extraction_confidence"]
        assert col.nullable

    def test_weight_is_float_with_default(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        col = GraphRelationshipModel.__table__.c["weight"]
        assert isinstance(col.type, sa.Float)
        assert col.server_default is not None

    def test_source_entity_fk_to_graph_entities(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        fks = GraphRelationshipModel.__table__.c["source_entity_id"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "graph_entities.id" in targets

    def test_target_entity_fk_to_graph_entities(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        fks = GraphRelationshipModel.__table__.c["target_entity_id"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "graph_entities.id" in targets

    def test_source_chunk_id_fk_to_chunks(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        fks = GraphRelationshipModel.__table__.c["source_chunk_id"].foreign_keys
        targets = {fk.target_fullname for fk in fks}
        assert "chunks.id" in targets

    def test_graph_version_has_server_default(self) -> None:
        from app.infrastructure.database.models.graph import GraphRelationshipModel

        col = GraphRelationshipModel.__table__.c["graph_version"]
        assert col.server_default is not None
