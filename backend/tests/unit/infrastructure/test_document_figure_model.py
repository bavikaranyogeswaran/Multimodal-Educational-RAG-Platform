"""Unit tests for migration 0015 and the document_figures ORM model.

Runs without a live database. Migration tests inspect source for the expected DDL;
model tests use SQLAlchemy's table introspection API.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

from app.infrastructure.database.models.figure import DocumentFigureModel

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_MIGRATION_FILE = "0015_document_figures.py"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration:
    def test_revision(self) -> None:
        assert _load_migration(_MIGRATION_FILE).revision == "0015"

    def test_down_revision_follows_the_previous_head(self) -> None:
        assert _load_migration(_MIGRATION_FILE).down_revision == "0014"

    def test_upgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).upgrade)

    def test_downgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).downgrade)

    def test_upgrade_creates_the_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert '"document_figures"' in src

    def test_downgrade_drops_the_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert 'op.drop_table("document_figures")' in src


class TestRowLevelSecurity:
    def test_row_level_security_is_enabled(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "ALTER TABLE document_figures ENABLE ROW LEVEL SECURITY" in src

    def test_the_isolation_policy_is_created(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "document_figures_user_isolation" in src

    def test_the_policy_checks_both_directions(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "USING (user_id = auth.uid())" in src
        assert "WITH CHECK (user_id = auth.uid())" in src

    def test_downgrade_drops_the_policy(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "DROP POLICY IF EXISTS document_figures_user_isolation" in src


class TestModel:
    def test_table_name(self) -> None:
        assert DocumentFigureModel.__tablename__ == "document_figures"

    def test_it_carries_both_scope_columns(self) -> None:
        columns = DocumentFigureModel.__table__.columns
        assert "user_id" in columns
        assert "knowledge_base_id" in columns

    def test_scope_columns_are_not_nullable(self) -> None:
        columns = DocumentFigureModel.__table__.columns
        assert columns["user_id"].nullable is False
        assert columns["knowledge_base_id"].nullable is False

    def test_it_stores_the_kind_discriminator(self) -> None:
        columns = DocumentFigureModel.__table__.columns
        assert "kind" in columns
        assert columns["kind"].nullable is False

    def test_it_stores_a_full_bounding_box(self) -> None:
        columns = DocumentFigureModel.__table__.columns
        for corner in ("x0", "y0", "x1", "y1"):
            assert f"bounding_box_{corner}" in columns
            assert columns[f"bounding_box_{corner}"].nullable is False

    def test_caption_and_number_are_nullable(self) -> None:
        # A detected visual may have no printed label.
        columns = DocumentFigureModel.__table__.columns
        assert columns["caption"].nullable is True
        assert columns["number"].nullable is True

    def test_chart_specific_columns_are_nullable(self) -> None:
        # These fields are absent for FIGURE and DIAGRAM kinds, and are filled
        # after image analysis rather than at detection time.
        columns = DocumentFigureModel.__table__.columns
        for col in ("title", "chart_type", "x_axis_label", "y_axis_label", "units_label"):
            assert columns[col].nullable is True, f"{col} should be nullable"

    def test_diagram_specific_columns_are_nullable(self) -> None:
        columns = DocumentFigureModel.__table__.columns
        for col in ("diagram_labels", "components", "arrows", "visible_relationships"):
            assert columns[col].nullable is True, f"{col} should be nullable"

    def test_the_document_foreign_key_cascades(self) -> None:
        fks = {fk.column.table.name: fk for fk in DocumentFigureModel.__table__.foreign_keys}
        assert fks["documents"].ondelete == "CASCADE"

    def test_the_element_foreign_key_cascades(self) -> None:
        fks = {fk.column.table.name: fk for fk in DocumentFigureModel.__table__.foreign_keys}
        assert fks["document_elements"].ondelete == "CASCADE"

    def test_it_indexes_the_document(self) -> None:
        names = {index.name for index in DocumentFigureModel.__table__.indexes}
        assert "ix_document_figures_document_id" in names

    def test_it_indexes_the_scope(self) -> None:
        names = {index.name for index in DocumentFigureModel.__table__.indexes}
        assert "ix_document_figures_user_id_kb_id" in names

    def test_it_indexes_its_source_element(self) -> None:
        names = {index.name for index in DocumentFigureModel.__table__.indexes}
        assert "ix_document_figures_source_element_id" in names

    def test_it_indexes_the_scoped_number(self) -> None:
        names = {index.name for index in DocumentFigureModel.__table__.indexes}
        assert "ix_document_figures_scope_number" in names

    def test_it_is_registered_with_the_shared_metadata(self) -> None:
        from app.infrastructure.database.base import Base

        assert "document_figures" in Base.metadata.tables
