"""Unit tests for migration 0008 — Row-Level Security policies.

Runs without a live database. All tests inspect migration source to verify
the expected DDL is present for every scoped table.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_MIGRATION_FILE = "0008_rls_policies.py"

_DIRECT_TABLES = [
    "knowledge_bases",
    "documents",
    "document_pages",
    "document_elements",
    "chunks",
    "conversations",
    "messages",
    "memory_facts",
    "graph_entities",
    "graph_relationships",
]

_BRIDGE_TABLES = [
    "chunk_elements",
    "conversation_retrieval_chunks",
]

_ALL_SCOPED_TABLES = _DIRECT_TABLES + _BRIDGE_TABLES

_SYSTEM_TABLES = ["processing_jobs", "cache_entries"]


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRLSMigration:
    def test_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.revision == "0008"

    def test_down_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.down_revision == "0007"

    def test_upgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).upgrade)

    def test_downgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).downgrade)


class TestRLSUpgrade:
    def test_enables_rls_on_every_scoped_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        for table in _ALL_SCOPED_TABLES:
            assert (
                f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in src
            ), f"Missing ENABLE ROW LEVEL SECURITY for {table}"

    def test_creates_named_policy_for_every_scoped_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        for table in _ALL_SCOPED_TABLES:
            assert (
                f"{table}_user_isolation" in src
            ), f"Missing policy name for {table}"

    def test_all_policies_use_for_all(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "FOR ALL" in src

    def test_all_policies_include_with_check(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "WITH CHECK" in src

    def test_direct_tables_use_auth_uid(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "auth.uid()" in src

    def test_bridge_tables_use_exists_subquery(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "EXISTS" in src

    def test_chunk_elements_delegates_through_chunks(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "FROM chunks" in src
        assert "chunk_elements.chunk_id" in src

    def test_conversation_retrieval_chunks_delegates_through_messages(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "FROM messages" in src
        assert "conversation_retrieval_chunks.message_id" in src

    def test_system_tables_not_in_upgrade(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        for table in _SYSTEM_TABLES:
            assert table not in src, f"System table {table} should not appear in upgrade"


class TestRLSDowngrade:
    def test_drops_policy_for_every_scoped_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        # Direct tables use an f-string loop so the policy names are not literal;
        # verify the naming template and every table name are present.
        assert "DROP POLICY IF EXISTS" in src
        assert "_user_isolation" in src
        for table in _ALL_SCOPED_TABLES:
            assert table in src, f"Table {table} missing from downgrade"

    def test_disables_rls_for_all_scoped_tables(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "DISABLE ROW LEVEL SECURITY" in src
        for table in _ALL_SCOPED_TABLES:
            assert table in src, f"Table {table} missing from downgrade"

    def test_uses_drop_policy_if_exists(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "DROP POLICY IF EXISTS" in src
