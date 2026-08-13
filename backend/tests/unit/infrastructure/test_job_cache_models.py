"""Unit tests for migration 0007 and job queue / cache ORM models.

Runs without a live database. Migration tests inspect source for expected SQL.
Model tests use SQLAlchemy's table introspection API.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"

_MIGRATION_FILE = "0007_job_queue_cache.py"


def _load_migration(filename: str) -> ModuleType:
    path = VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestJobCacheMigration:
    def test_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.revision == "0007"

    def test_down_revision(self) -> None:
        mod = _load_migration(_MIGRATION_FILE)
        assert mod.down_revision == "0006"

    def test_upgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).upgrade)

    def test_downgrade_is_callable(self) -> None:
        assert callable(_load_migration(_MIGRATION_FILE).downgrade)

    def test_upgrade_creates_processing_jobs_table(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "processing_jobs" in src
        assert "job_type" in src
        assert "payload" in src

    def test_upgrade_creates_claim_index(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "ix_processing_jobs_claim" in src

    def test_upgrade_creates_cache_entries_unlogged(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "UNLOGGED" in src
        assert "cache_entries" in src

    def test_cache_entries_has_partial_expires_at_index(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "ix_cache_entries_expires_at" in src
        assert "WHERE expires_at IS NOT NULL" in src

    def test_pg_cron_sweep_scheduled(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).upgrade)
        assert "cron.schedule" in src
        assert "sweep-expired-cache" in src

    def test_downgrade_unschedules_pg_cron(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "cron.unschedule" in src
        assert "sweep-expired-cache" in src

    def test_downgrade_drops_processing_jobs(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "processing_jobs" in src

    def test_downgrade_drops_cache_entries(self) -> None:
        src = inspect.getsource(_load_migration(_MIGRATION_FILE).downgrade)
        assert "cache_entries" in src


class TestProcessingJobModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        assert ProcessingJobModel.__tablename__ == "processing_jobs"

    def test_has_claim_index(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        index_names = {idx.name for idx in ProcessingJobModel.__table__.indexes}
        assert "ix_processing_jobs_claim" in index_names

    def test_claim_index_covers_status_and_priority(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        idx = next(
            i
            for i in ProcessingJobModel.__table__.indexes
            if i.name == "ix_processing_jobs_claim"
        )
        col_names = [c.name for c in idx.columns]
        assert col_names == ["status", "priority"]

    def test_payload_is_jsonb(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        col = ProcessingJobModel.__table__.c["payload"]
        assert isinstance(col.type, JSONB)

    def test_nullable_timestamp_columns(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        for name in ("scheduled_at", "lease_expires_at", "last_heartbeat_at"):
            col = ProcessingJobModel.__table__.c[name]
            assert col.nullable, f"{name} should be nullable"

    def test_failure_reason_is_nullable(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        col = ProcessingJobModel.__table__.c["failure_reason"]
        assert col.nullable

    def test_core_columns_are_not_nullable(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        for name in ("job_type", "priority", "status", "attempt_count", "max_attempts", "payload"):
            col = ProcessingJobModel.__table__.c[name]
            assert not col.nullable, f"{name} should be NOT NULL"

    def test_priority_stored_as_integer(self) -> None:
        from app.infrastructure.database.models.job import ProcessingJobModel

        col = ProcessingJobModel.__table__.c["priority"]
        assert isinstance(col.type, sa.Integer)


class TestCacheEntryModel:
    def test_tablename(self) -> None:
        from app.infrastructure.database.models.job import CacheEntryModel

        assert CacheEntryModel.__tablename__ == "cache_entries"

    def test_key_is_primary_key(self) -> None:
        from app.infrastructure.database.models.job import CacheEntryModel

        pk_cols = {c.name for c in CacheEntryModel.__table__.primary_key.columns}
        assert pk_cols == {"key"}

    def test_value_is_not_nullable(self) -> None:
        from app.infrastructure.database.models.job import CacheEntryModel

        col = CacheEntryModel.__table__.c["value"]
        assert not col.nullable

    def test_value_is_binary(self) -> None:
        from app.infrastructure.database.models.job import CacheEntryModel

        col = CacheEntryModel.__table__.c["value"]
        assert isinstance(col.type, sa.LargeBinary)

    def test_expires_at_is_nullable(self) -> None:
        from app.infrastructure.database.models.job import CacheEntryModel

        col = CacheEntryModel.__table__.c["expires_at"]
        assert col.nullable

    def test_table_is_declared_unlogged(self) -> None:
        from app.infrastructure.database.models.job import CacheEntryModel

        # SQLAlchemy has no Table kwarg for UNLOGGED; the flag is applied by the
        # migration's raw SQL. The docstring is the canonical model-level signal.
        assert "UNLOGGED" in (CacheEntryModel.__doc__ or "")
