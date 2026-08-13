"""Unit tests for DocumentElement, Chunk and ChunkElement ORM models.

Runs without a live database. Verifies table registration, key column types,
nullable constraints, FK wiring, and migration revision metadata.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR

from app.infrastructure.database.base import Base
from app.infrastructure.database.models import ChunkElementModel, ChunkModel, DocumentElementModel

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDocumentElementModel:
    def test_table_name(self) -> None:
        assert DocumentElementModel.__tablename__ == "document_elements"

    def test_table_registered(self) -> None:
        assert "document_elements" in Base.metadata.tables

    def test_primary_key_is_id(self) -> None:
        table = Base.metadata.tables["document_elements"]
        assert "id" in table.primary_key.columns

    def test_document_id_has_fk_to_documents(self) -> None:
        table = Base.metadata.tables["document_elements"]
        fk_targets = {fk.target_fullname for fk in table.c.document_id.foreign_keys}
        assert "documents.id" in fk_targets

    def test_text_is_not_nullable(self) -> None:
        table = Base.metadata.tables["document_elements"]
        assert not table.c.text.nullable

    def test_confidence_is_nullable(self) -> None:
        table = Base.metadata.tables["document_elements"]
        assert table.c.confidence.nullable

    def test_bounding_box_columns_are_nullable(self) -> None:
        table = Base.metadata.tables["document_elements"]
        for col in ("bounding_box_x0", "bounding_box_y0", "bounding_box_x1", "bounding_box_y1"):
            assert table.c[col].nullable, f"{col} should be nullable"

    def test_heading_path_is_array(self) -> None:
        table = Base.metadata.tables["document_elements"]
        assert isinstance(table.c.heading_path.type, ARRAY)

    def test_heading_path_has_server_default(self) -> None:
        table = Base.metadata.tables["document_elements"]
        assert table.c.heading_path.server_default is not None

    def test_document_id_index_exists(self) -> None:
        table = Base.metadata.tables["document_elements"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_document_elements_document_id" in index_names

    def test_user_id_kb_id_composite_index_exists(self) -> None:
        table = Base.metadata.tables["document_elements"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_document_elements_user_id_kb_id" in index_names


class TestChunkModel:
    def test_table_name(self) -> None:
        assert ChunkModel.__tablename__ == "chunks"

    def test_table_registered(self) -> None:
        assert "chunks" in Base.metadata.tables

    def test_document_id_has_fk_to_documents(self) -> None:
        table = Base.metadata.tables["chunks"]
        fk_targets = {fk.target_fullname for fk in table.c.document_id.foreign_keys}
        assert "documents.id" in fk_targets

    def test_parent_chunk_id_is_self_referential(self) -> None:
        table = Base.metadata.tables["chunks"]
        fk_targets = {fk.target_fullname for fk in table.c.parent_chunk_id.foreign_keys}
        assert "chunks.id" in fk_targets

    def test_source_element_id_has_fk_to_document_elements(self) -> None:
        table = Base.metadata.tables["chunks"]
        fk_targets = {fk.target_fullname for fk in table.c.source_element_id.foreign_keys}
        assert "document_elements.id" in fk_targets

    def test_parent_chunk_id_is_nullable(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert table.c.parent_chunk_id.nullable

    def test_tsv_is_tsvector(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert isinstance(table.c.tsv.type, TSVECTOR)

    def test_tsv_is_nullable(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert table.c.tsv.nullable

    def test_heading_path_is_array_with_server_default(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert isinstance(table.c.heading_path.type, ARRAY)
        assert table.c.heading_path.server_default is not None

    def test_embedding_is_nullable(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert table.c.embedding.nullable

    def test_index_version_has_server_default(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert table.c.index_version.server_default is not None

    def test_token_count_is_not_nullable(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert not table.c.token_count.nullable

    def test_text_is_not_nullable(self) -> None:
        table = Base.metadata.tables["chunks"]
        assert not table.c.text.nullable

    def test_document_id_index_exists(self) -> None:
        table = Base.metadata.tables["chunks"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_chunks_document_id" in index_names

    def test_user_id_kb_id_composite_index_exists(self) -> None:
        table = Base.metadata.tables["chunks"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_chunks_user_id_kb_id" in index_names

    def test_parent_chunk_id_index_exists(self) -> None:
        table = Base.metadata.tables["chunks"]
        index_names = {idx.name for idx in table.indexes}
        assert "ix_chunks_parent_chunk_id" in index_names


class TestChunkElementModel:
    def test_table_name(self) -> None:
        assert ChunkElementModel.__tablename__ == "chunk_elements"

    def test_table_registered(self) -> None:
        assert "chunk_elements" in Base.metadata.tables

    def test_chunk_id_has_fk_to_chunks(self) -> None:
        table = Base.metadata.tables["chunk_elements"]
        fk_targets = {fk.target_fullname for fk in table.c.chunk_id.foreign_keys}
        assert "chunks.id" in fk_targets

    def test_element_id_has_fk_to_document_elements(self) -> None:
        table = Base.metadata.tables["chunk_elements"]
        fk_targets = {fk.target_fullname for fk in table.c.element_id.foreign_keys}
        assert "document_elements.id" in fk_targets

    def test_composite_primary_key(self) -> None:
        table = Base.metadata.tables["chunk_elements"]
        pk_cols = {col.name for col in table.primary_key.columns}
        assert pk_cols == {"chunk_id", "element_id"}


class TestChunksMigration:
    def test_revision_is_0003(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        assert mod.revision == "0003"

    def test_down_revision_is_0002(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        assert mod.down_revision == "0002"

    def test_upgrade_is_callable(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        assert callable(mod.upgrade)

    def test_downgrade_is_callable(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        assert callable(mod.downgrade)

    def test_upgrade_covers_all_three_tables(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        src = inspect.getsource(mod.upgrade)
        for table in ("document_elements", "chunks", "chunk_elements"):
            assert table in src, f"upgrade() does not create the '{table}' table"

    def test_upgrade_creates_tsvector_trigger(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        src = inspect.getsource(mod.upgrade)
        assert "chunks_tsv_update" in src
        assert "chunks_tsv_trigger" in src

    def test_downgrade_drops_all_three_tables(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        src = inspect.getsource(mod.downgrade)
        for table in ("document_elements", "chunks", "chunk_elements"):
            assert table in src, f"downgrade() does not drop the '{table}' table"

    def test_downgrade_drops_trigger(self) -> None:
        mod = _load_migration("0003_document_elements_chunks.py")
        src = inspect.getsource(mod.downgrade)
        assert "chunks_tsv_trigger" in src
        assert "chunks_tsv_update" in src
