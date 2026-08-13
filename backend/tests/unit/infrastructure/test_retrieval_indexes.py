"""Unit tests for migration 0004 — retrieval indexes.

Runs without a live database. Verifies the migration source contains the correct
index definitions: one HNSW, one RUM, and six composite B-tree scoped indexes.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_SIX_COMPOSITE_INDEXES = [
    "ix_chunks_scope_document_id",
    "ix_chunks_scope_chunk_type",
    "ix_chunks_scope_index_version",
    "ix_chunks_scope_language",
    "ix_chunks_scope_ordinal",
    "ix_chunks_scope_content_hash",
]


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRetrievalIndexesMigration:
    def test_revision(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        assert mod.revision == "0004"

    def test_down_revision(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        assert mod.down_revision == "0003"

    def test_upgrade_is_callable(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        assert callable(mod.upgrade)

    def test_downgrade_is_callable(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        assert callable(mod.downgrade)

    def test_upgrade_creates_hnsw_index(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        src = inspect.getsource(mod.upgrade)
        assert "ix_chunks_embedding_hnsw" in src
        assert "hnsw" in src
        assert "vector_cosine_ops" in src
        assert "m = 16" in src
        assert "ef_construction = 128" in src

    def test_upgrade_creates_rum_index(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        src = inspect.getsource(mod.upgrade)
        assert "ix_chunks_tsv_rum" in src
        assert "rum" in src
        assert "rum_tsvector_ops" in src

    def test_upgrade_creates_all_six_composite_indexes(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        src = inspect.getsource(mod.upgrade)
        for name in _SIX_COMPOSITE_INDEXES:
            assert name in src, f"upgrade() is missing composite index '{name}'"

    def test_downgrade_drops_hnsw_index(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        src = inspect.getsource(mod.downgrade)
        assert "ix_chunks_embedding_hnsw" in src

    def test_downgrade_drops_rum_index(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        src = inspect.getsource(mod.downgrade)
        assert "ix_chunks_tsv_rum" in src

    def test_downgrade_drops_all_six_composite_indexes(self) -> None:
        mod = _load_migration("0004_retrieval_indexes.py")
        src = inspect.getsource(mod.downgrade)
        for name in _SIX_COMPOSITE_INDEXES:
            assert name in src, f"downgrade() does not drop composite index '{name}'"
