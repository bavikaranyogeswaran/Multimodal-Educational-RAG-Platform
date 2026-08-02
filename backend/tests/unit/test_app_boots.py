"""The application starts and serves its liveness probe."""

from __future__ import annotations

from starlette.testclient import TestClient

from app.main import API_PREFIX, app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": app.version}


def test_openapi_schema_is_served_under_the_api_prefix(client: TestClient) -> None:
    """FR-API-01 — the API is versioned under /api/v1."""
    response = client.get(f"{API_PREFIX}/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Multimodal Educational Tutor RAG"


async def test_lifespan_runs() -> None:
    """The lifespan hook completes — Phase 8 hangs model warm-up off it (FR-PRF-02)."""
    async with app.router.lifespan_context(app):
        pass
