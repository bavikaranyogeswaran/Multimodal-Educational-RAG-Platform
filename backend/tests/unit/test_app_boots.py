"""The application starts and serves its liveness probe."""

from __future__ import annotations

from starlette.testclient import TestClient

from app.main import API_PREFIX, app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": app.version}


def test_openapi_schema_is_served_under_the_api_prefix(client: TestClient) -> None:
    """The API is versioned, and the schema lives under the same prefix as the routes."""
    response = client.get(f"{API_PREFIX}/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Multimodal Educational Tutor RAG"


async def test_lifespan_runs() -> None:
    """The lifespan hook completes — model warm-up hangs off it later."""
    async with app.router.lifespan_context(app):
        pass
