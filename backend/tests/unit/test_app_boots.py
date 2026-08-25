"""The application starts and serves its liveness probe."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from app import main
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


# ---------------------------------------------------------------------------
# Knowledge Bases whose index is not the one this build writes
# ---------------------------------------------------------------------------


def _session_factory(rows: list[tuple[uuid.UUID, int]] | Exception) -> MagicMock:
    session = AsyncMock()
    if isinstance(rows, Exception):
        session.execute = AsyncMock(side_effect=rows)
    else:
        result = MagicMock()
        result.all.return_value = rows
        session.execute = AsyncMock(return_value=result)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _settings(version: int = 2) -> MagicMock:
    settings = MagicMock()
    settings.embedding.index_version = version
    return settings


class TestStaleIndexReport:
    """A reconfigured embedding model has no symptom of its own.

    Everything keeps working and documents added afterwards are simply never found.
    Uploads are refused while it lasts, but a refusal only reaches whoever tries next;
    saying it at startup reaches whoever changed the setting.
    """

    async def test_says_nothing_when_every_index_matches(self) -> None:
        with patch.object(main, "_log") as log:
            await main._report_stale_indexes(_session_factory([]), _settings())

        log.warning.assert_not_called()

    async def test_names_the_knowledge_bases_that_need_rebuilding(self) -> None:
        kb_id = uuid.uuid4()

        with patch.object(main, "_log") as log:
            await main._report_stale_indexes(_session_factory([(kb_id, 1)]), _settings(2))

        log.warning.assert_called_once()
        payload = log.warning.call_args.kwargs
        assert payload["written_version"] == 2
        assert payload["knowledge_bases"] == [{"id": str(kb_id), "active_index_version": 1}]

    async def test_a_database_that_cannot_be_read_does_not_stop_startup(self) -> None:
        """This is a diagnostic. One that can stop the server starting is worse than the
        condition it reports."""
        factory = _session_factory(RuntimeError("the database is unreachable"))

        with patch.object(main, "_log") as log:
            await main._report_stale_indexes(factory, _settings())

        log.warning.assert_called_once()
        assert log.warning.call_args.args[0] == "stale_index_check_failed"
