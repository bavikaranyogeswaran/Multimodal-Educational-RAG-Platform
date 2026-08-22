"""Unit tests for migration 0012 and the document_tables ORM model.

Runs without a live database. Migration tests inspect source for the expected DDL;
model tests use SQLAlchemy's table introspection API.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

from app.infrastructure.database.models.table import DocumentTableModel

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_MIGRATION_FILE = "0012_document_tables.py"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration:
    def test_revision(self) -> None:
        assert _load_migration(_MIGRATION_FILE).revision == "0012"

    def test_down_revision_follows_the_previous_head(self) -> None:
        assert _load_migration(_MIGRATION_FILE).down_revision == "0011"

    def test_upgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).upgrade)

    def test_downgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).downgrade)

    def test_upgrade_creates_the_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"document_tables"' in src

    def test_downgrade_drops_the_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert 'op.drop_table("document_tables")' in src


class TestRowLevelSecurity:
    def test_row_level_security_is_enabled(self) -> None:
        # A new scoped table without this is readable across users. The enumeration test
        # that guards the original ten tables is pinned to its own migration, so it
        # cannot catch a table added later — this check is what covers this one.
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "ALTER TABLE document_tables ENABLE ROW LEVEL SECURITY" in src

    def test_the_isolation_policy_is_created(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "document_tables_user_isolation" in src

    def test_the_policy_checks_both_directions(self) -> None:
        # USING alone filters reads; without WITH CHECK a row can still be written
        # under another user's id.
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "USING (user_id = auth.uid())" in src
        assert "WITH CHECK (user_id = auth.uid())" in src

    def test_downgrade_drops_the_policy(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "DROP POLICY IF EXISTS document_tables_user_isolation" in src


class TestModel:
    def test_table_name(self) -> None:
        assert DocumentTableModel.__tablename__ == "document_tables"

    def test_it_carries_both_scope_columns(self) -> None:
        columns = DocumentTableModel.__table__.columns
        assert "user_id" in columns
        assert "knowledge_base_id" in columns

    def test_scope_columns_are_not_nullable(self) -> None:
        columns = DocumentTableModel.__table__.columns
        assert columns["user_id"].nullable is False
        assert columns["knowledge_base_id"].nullable is False

    def test_it_stores_the_grid(self) -> None:
        columns = DocumentTableModel.__table__.columns
        assert "headers" in columns
        assert "units" in columns
        assert "rows" in columns

    def test_units_are_nullable_because_most_columns_have_none(self) -> None:
        assert DocumentTableModel.__table__.columns["units"].nullable is True

    def test_headers_are_not_nullable(self) -> None:
        # Rows without headers cannot be read back, so the entity refuses them and the
        # schema says the same thing.
        assert DocumentTableModel.__table__.columns["headers"].nullable is False

    def test_it_stores_a_full_bounding_box(self) -> None:
        columns = DocumentTableModel.__table__.columns
        for corner in ("x0", "y0", "x1", "y1"):
            assert f"bounding_box_{corner}" in columns
            # A table always has a region, unlike an element, which may be OCR-free text.
            assert columns[f"bounding_box_{corner}"].nullable is False

    def test_the_document_foreign_key_cascades(self) -> None:
        fks = {fk.column.table.name: fk for fk in DocumentTableModel.__table__.foreign_keys}
        assert fks["documents"].ondelete == "CASCADE"

    def test_the_element_foreign_key_cascades(self) -> None:
        # Not SET NULL: without its element the table has no region on the page, and a
        # record that cannot be located can be neither cited nor highlighted.
        fks = {fk.column.table.name: fk for fk in DocumentTableModel.__table__.foreign_keys}
        assert fks["document_elements"].ondelete == "CASCADE"

    def test_it_indexes_the_scope(self) -> None:
        names = {index.name for index in DocumentTableModel.__table__.indexes}
        assert "ix_document_tables_user_id_kb_id" in names

    def test_it_indexes_its_source_element(self) -> None:
        names = {index.name for index in DocumentTableModel.__table__.indexes}
        assert "ix_document_tables_source_element_id" in names

    def test_it_is_registered_with_the_shared_metadata(self) -> None:
        from app.infrastructure.database.base import Base

        assert "document_tables" in Base.metadata.tables


_RENDERINGS_MIGRATION = "0013_document_table_renderings.py"


class TestRenderingsMigration:
    def test_revision(self) -> None:
        assert _load_migration(_RENDERINGS_MIGRATION).revision == "0013"

    def test_down_revision_follows_the_table_migration(self) -> None:
        assert _load_migration(_RENDERINGS_MIGRATION).down_revision == "0012"

    def test_it_adds_every_rendered_form(self) -> None:
        src = inspect.getsource(_load_migration(_RENDERINGS_MIGRATION).upgrade)
        for column in ("table_json", "markdown", "html", "embedding_text"):
            assert f'"{column}"' in src

    def test_the_columns_are_nullable(self) -> None:
        # A table exists as a grid before it is rendered, and rows written before this
        # migration have no renderings at all.
        src = inspect.getsource(_load_migration(_RENDERINGS_MIGRATION).upgrade)
        assert "nullable=False" not in src

    def test_downgrade_drops_every_column_it_added(self) -> None:
        src = inspect.getsource(_load_migration(_RENDERINGS_MIGRATION).downgrade)
        for column in ("table_json", "markdown", "html", "embedding_text"):
            assert f'"{column}"' in src


class TestRenderingColumns:
    def test_the_model_carries_every_rendered_form(self) -> None:
        columns = DocumentTableModel.__table__.columns
        for column in ("table_json", "markdown", "html", "embedding_text"):
            assert column in columns

    def test_they_are_all_nullable(self) -> None:
        columns = DocumentTableModel.__table__.columns
        for column in ("table_json", "markdown", "html", "embedding_text"):
            assert columns[column].nullable is True

    def test_table_json_is_text_not_jsonb(self) -> None:
        # Nothing queries inside it, unlike `rows`, and storing the exact string keeps
        # it identical to what a caller was handed.
        assert "JSON" not in str(DocumentTableModel.__table__.columns["table_json"].type)


_NUMBER_MIGRATION = "0014_document_table_number.py"


class TestNumberMigration:
    def test_revision(self) -> None:
        assert _load_migration(_NUMBER_MIGRATION).revision == "0014"

    def test_down_revision_follows_the_renderings_migration(self) -> None:
        assert _load_migration(_NUMBER_MIGRATION).down_revision == "0013"

    def test_it_adds_the_number_column(self) -> None:
        src = inspect.getsource(_load_migration(_NUMBER_MIGRATION).upgrade)
        assert '"number"' in src

    def test_the_column_is_nullable(self) -> None:
        # Plenty of tables are printed with no number at all.
        src = inspect.getsource(_load_migration(_NUMBER_MIGRATION).upgrade)
        assert "nullable=True" in src

    def test_it_indexes_the_number_within_its_scope(self) -> None:
        # Looking a table up by number is a scoped lookup, and that is the access path
        # this column exists to serve.
        src = inspect.getsource(_load_migration(_NUMBER_MIGRATION).upgrade)
        assert "ix_document_tables_scope_number" in src
        assert '"user_id", "knowledge_base_id", "number"' in src

    def test_downgrade_removes_both_the_index_and_the_column(self) -> None:
        src = inspect.getsource(_load_migration(_NUMBER_MIGRATION).downgrade)
        assert "ix_document_tables_scope_number" in src
        assert '"number"' in src


class TestNumberColumn:
    def test_the_model_carries_the_number(self) -> None:
        assert "number" in DocumentTableModel.__table__.columns

    def test_it_is_nullable(self) -> None:
        assert DocumentTableModel.__table__.columns["number"].nullable is True

    def test_it_is_text_rather_than_numeric(self) -> None:
        # "4.2", "A.1" and "2b" are all real table numbers, and none of them is a number.
        assert "TEXT" in str(DocumentTableModel.__table__.columns["number"].type).upper()

    def test_the_scoped_number_index_is_declared(self) -> None:
        names = {index.name for index in DocumentTableModel.__table__.indexes}
        assert "ix_document_tables_scope_number" in names
