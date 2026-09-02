"""Migration chain tests against the live PostgreSQL database.

test_migrations_at_head (non-destructive):
    Reads alembic_version from the live database and asserts the current
    revision matches the expected head. Fails fast if migrations were applied
    out of order or the database is behind.

test_migration_round_trip (destructive, opt-in):
    Drops the entire schema (downgrade base) then re-creates it (upgrade head)
    to confirm the full chain is idempotent. This destroys all data in the
    database. It is skipped unless the environment variable
    ALLOW_DESTRUCTIVE_MIGRATION_TEST=1 is set. Only run this against a
    dedicated test database, never against staging or production.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_BACKEND_DIR = Path(__file__).parent.parent.parent  # backend/


def _expected_head() -> str:
    """The head revision according to the migration files themselves.

    Read from the script directory rather than written down here. A constant someone has
    to remember to bump after every migration is a constant that goes stale silently —
    this one sat at 0008 through two migrations, and only surfaced when these tests were
    first run again. What the test means is "the database is at whatever the migrations
    say is current", so that is what it now asks.
    """
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head is not None, "no alembic head revision found"
    return head


# ---------------------------------------------------------------------------
# non-destructive: verify current revision
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_migrations_at_head(test_db_url: str) -> None:
    """The alembic_version table must contain exactly the head revision."""
    engine = create_async_engine(test_db_url, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT version_num FROM alembic_version")
        )
        version = result.scalar_one()
    await engine.dispose()

    expected = _expected_head()
    assert version == expected, (
        f"Expected head revision {expected!r}, got {version!r}. "
        "Run: uv run alembic upgrade head"
    )


# ---------------------------------------------------------------------------
# destructive: full downgrade → upgrade round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
def test_migration_round_trip(test_db_url_raw: str) -> None:
    """Drop all schema and rebuild it to confirm every migration is reversible.

    Guarded by ALLOW_DESTRUCTIVE_MIGRATION_TEST=1 because this wipes the
    entire database. Only use it against a disposable test instance.
    """
    if not os.getenv("ALLOW_DESTRUCTIVE_MIGRATION_TEST"):
        pytest.skip(
            "Set ALLOW_DESTRUCTIVE_MIGRATION_TEST=1 to enable the destructive "
            "round-trip test. Only run it against a dedicated test database."
        )

    env = {**os.environ, "DATABASE_URL": test_db_url_raw}
    cwd = str(_BACKEND_DIR)

    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True, check=False,
    )
    assert down.returncode == 0, (
        f"alembic downgrade base failed (exit {down.returncode}):\n{down.stderr}"
    )

    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True, check=False,
    )
    assert up.returncode == 0, (
        f"alembic upgrade head failed (exit {up.returncode}):\n{up.stderr}"
    )
