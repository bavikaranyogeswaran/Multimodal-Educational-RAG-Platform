"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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
