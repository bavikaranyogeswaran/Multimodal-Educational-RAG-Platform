"""Shared pytest fixtures, and the event loop every test runs on.

The loop is settled here, before pytest-asyncio creates one, because the application
cannot run on the loop Windows would otherwise supply: psycopg refuses it outright for
async connections. Tests that ran on a loop the application refuses would be exercising
an arrangement that cannot exist, and the startup check in the API would fail against
the suite while passing in every configuration anyone actually runs.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from starlette.testclient import TestClient

from app.main import app

APP_ROOT = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture(scope="session")
def app_root() -> Path:
    """Filesystem root of the application package."""
    return APP_ROOT


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Synchronous test client against the FastAPI application."""
    with TestClient(app) as test_client:
        yield test_client
