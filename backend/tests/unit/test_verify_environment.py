"""The verification script's own logic, which is easy to break silently."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_environment.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    """Load the script by path — it lives outside the importable package."""
    spec = importlib.util.spec_from_file_location("verify_environment", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_environment"] = module
    spec.loader.exec_module(module)
    return module


def test_script_exists() -> None:
    assert SCRIPT.is_file()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql+psycopg://user:pw@host:6543/postgres",
            "postgresql://user:pw@host:6543/postgres",
        ),
        (
            "postgres+psycopg://user:pw@host:5432/db",
            "postgresql://user:pw@host:5432/db",
        ),
        # Already a libpq DSN, so it must pass through untouched.
        ("postgresql://user:pw@host:5432/db", "postgresql://user:pw@host:5432/db"),
    ],
)
def test_sqlalchemy_url_is_converted_to_a_libpq_dsn(
    script: ModuleType, given: str, expected: str
) -> None:
    """libpq rejects the driver suffix SQLAlchemy requires, so it has to be stripped."""
    assert script._psycopg_dsn(given) == expected


def test_required_extensions_cover_what_the_schema_needs(script: ModuleType) -> None:
    """Missing one of these at migration time is a confusing failure much later."""
    assert set(script.REQUIRED_EXTENSIONS) == {"vector", "rum", "pg_cron", "pg_trgm"}


def test_unconfigured_services_report_skip_not_fail(script: ModuleType) -> None:
    """An unconfigured machine must not look like a broken one."""
    assert script.Status.SKIP != script.Status.FAIL
    assert {s.value for s in script.Status} == {"PASS", "FAIL", "SKIP", "WARN"}
