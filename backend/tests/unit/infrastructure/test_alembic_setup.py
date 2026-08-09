"""Unit tests for the Alembic configuration and first migration.

These run without a live database. They verify that the declarative Base is
importable, that metadata is correctly configured, and that the first migration
file has the expected structure. Full round-trip (upgrade → downgrade → upgrade)
lives in the integration suite at step 2.12.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase

from app.infrastructure.database.base import Base

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDeclarativeBase:
    def test_base_is_importable(self) -> None:
        assert issubclass(Base, DeclarativeBase)

    def test_base_exposes_metadata(self) -> None:
        assert isinstance(Base.metadata, sa.MetaData)

    def test_metadata_starts_empty(self) -> None:
        # No ORM models exist yet; the metadata table registry is empty.
        assert len(Base.metadata.tables) == 0


class TestExtensionMigration:
    def test_revision_is_0001(self) -> None:
        mod = _load_migration("0001_activate_extensions.py")
        assert mod.revision == "0001"

    def test_is_root_migration(self) -> None:
        mod = _load_migration("0001_activate_extensions.py")
        assert mod.down_revision is None

    def test_upgrade_is_callable(self) -> None:
        mod = _load_migration("0001_activate_extensions.py")
        assert callable(mod.upgrade)

    def test_downgrade_is_callable(self) -> None:
        mod = _load_migration("0001_activate_extensions.py")
        assert callable(mod.downgrade)

    def test_upgrade_sql_covers_all_four_extensions(self) -> None:
        mod = _load_migration("0001_activate_extensions.py")
        src = inspect.getsource(mod.upgrade)
        for ext in ("vector", "rum", "pg_cron", "pg_trgm"):
            assert ext in src, f"upgrade() does not activate the '{ext}' extension"

    def test_downgrade_is_intentional_noop(self) -> None:
        mod = _load_migration("0001_activate_extensions.py")
        # Strip comment lines before checking — the comment text explains why
        # dropping is skipped, so it naturally contains the word.
        executable = "\n".join(
            line
            for line in inspect.getsource(mod.downgrade).splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "DROP" not in executable.upper()
