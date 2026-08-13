"""Unit tests for KnowledgeBase, Document and DocumentPage ORM models.

These run without a live database. They verify that each model class registers
the correct table in Base.metadata, that key columns have the expected types
and nullability, and that FK constraints wire documents → knowledge_bases and
document_pages → documents.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import DocumentModel, DocumentPageModel, KnowledgeBaseModel

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestKnowledgeBaseModel:
    def test_table_name(self) -> None:
        assert KnowledgeBaseModel.__tablename__ == "knowledge_bases"

    def test_table_registered(self) -> None:
        assert "knowledge_bases" in Base.metadata.tables

    def test_primary_key_is_id(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        assert "id" in table.primary_key.columns

    def test_user_id_is_not_nullable(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        assert not table.c.user_id.nullable

    def test_name_max_length_is_200(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        col_type = table.c.name.type
        assert isinstance(col_type, sa.String)
        assert col_type.length == 200

    def test_description_is_nullable(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        assert table.c.description.nullable

    def test_explanation_level_has_server_default(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        assert table.c.explanation_level.server_default is not None

    def test_graph_enabled_has_server_default(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        assert table.c.graph_enabled.server_default is not None

    def test_created_at_is_timezone_aware(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        col_type = table.c.created_at.type
        assert isinstance(col_type, sa.DateTime)
        assert col_type.timezone

    def test_user_id_index_exists(self) -> None:
        table = Base.metadata.tables["knowledge_bases"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_knowledge_bases_user_id" in index_names


class TestDocumentModel:
    def test_table_name(self) -> None:
        assert DocumentModel.__tablename__ == "documents"

    def test_table_registered(self) -> None:
        assert "documents" in Base.metadata.tables

    def test_knowledge_base_id_has_fk_to_knowledge_bases(self) -> None:
        table = Base.metadata.tables["documents"]
        fk_targets = {fk.target_fullname for fk in table.c.knowledge_base_id.foreign_keys}
        assert "knowledge_bases.id" in fk_targets

    def test_byte_size_is_biginteger(self) -> None:
        table = Base.metadata.tables["documents"]
        assert isinstance(table.c.byte_size.type, sa.BigInteger)

    def test_status_has_server_default(self) -> None:
        table = Base.metadata.tables["documents"]
        assert table.c.status.server_default is not None

    def test_processed_at_is_nullable(self) -> None:
        table = Base.metadata.tables["documents"]
        assert table.c.processed_at.nullable

    def test_failure_reason_is_nullable(self) -> None:
        table = Base.metadata.tables["documents"]
        assert table.c.failure_reason.nullable

    def test_filename_is_not_nullable(self) -> None:
        table = Base.metadata.tables["documents"]
        assert not table.c.filename.nullable

    def test_user_id_kb_id_composite_index_exists(self) -> None:
        table = Base.metadata.tables["documents"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_documents_user_id_kb_id" in index_names


class TestDocumentPageModel:
    def test_table_name(self) -> None:
        assert DocumentPageModel.__tablename__ == "document_pages"

    def test_table_registered(self) -> None:
        assert "document_pages" in Base.metadata.tables

    def test_document_id_has_fk_to_documents(self) -> None:
        table = Base.metadata.tables["document_pages"]
        fk_targets = {fk.target_fullname for fk in table.c.document_id.foreign_keys}
        assert "documents.id" in fk_targets

    def test_width_is_float(self) -> None:
        table = Base.metadata.tables["document_pages"]
        assert isinstance(table.c.width.type, sa.Float)

    def test_height_is_float(self) -> None:
        table = Base.metadata.tables["document_pages"]
        assert isinstance(table.c.height.type, sa.Float)

    def test_rotation_has_server_default(self) -> None:
        table = Base.metadata.tables["document_pages"]
        assert table.c.rotation.server_default is not None

    def test_ocr_confidence_is_nullable(self) -> None:
        table = Base.metadata.tables["document_pages"]
        assert table.c.ocr_confidence.nullable

    def test_page_number_is_not_nullable(self) -> None:
        table = Base.metadata.tables["document_pages"]
        assert not table.c.page_number.nullable

    def test_document_id_index_exists(self) -> None:
        table = Base.metadata.tables["document_pages"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_document_pages_document_id" in index_names

    def test_user_id_kb_id_composite_index_exists(self) -> None:
        table = Base.metadata.tables["document_pages"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_document_pages_user_id_kb_id" in index_names


class TestSchemasMigration:
    def test_revision_is_0002(self) -> None:
        mod = _load_migration("0002_knowledge_bases_documents_pages.py")
        assert mod.revision == "0002"

    def test_down_revision_is_0001(self) -> None:
        mod = _load_migration("0002_knowledge_bases_documents_pages.py")
        assert mod.down_revision == "0001"

    def test_upgrade_is_callable(self) -> None:
        mod = _load_migration("0002_knowledge_bases_documents_pages.py")
        assert callable(mod.upgrade)

    def test_downgrade_is_callable(self) -> None:
        mod = _load_migration("0002_knowledge_bases_documents_pages.py")
        assert callable(mod.downgrade)

    def test_upgrade_covers_all_three_tables(self) -> None:
        mod = _load_migration("0002_knowledge_bases_documents_pages.py")
        src = inspect.getsource(mod.upgrade)
        for table in ("knowledge_bases", "documents", "document_pages"):
            assert table in src, f"upgrade() does not create the '{table}' table"

    def test_downgrade_drops_all_three_tables(self) -> None:
        mod = _load_migration("0002_knowledge_bases_documents_pages.py")
        src = inspect.getsource(mod.downgrade)
        for table in ("knowledge_bases", "documents", "document_pages"):
            assert table in src, f"downgrade() does not drop the '{table}' table"
