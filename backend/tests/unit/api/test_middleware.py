"""Unit tests for TraceIDMiddleware, RequestLoggingMiddleware, and exception handlers.

All tests use a minimal FastAPI app assembled inline so no server, database, or
JWKS endpoint is needed.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.api.middleware.errors import register_exception_handlers
from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.middleware.trace import TraceIDMiddleware
from app.domain.errors import (
    AuthenticationError,
    InvariantViolationError,
    NotFoundError,
    ScopeViolationError,
)


def _make_app() -> FastAPI:
    """Minimal app with the full middleware stack and one route per error type."""
    test_app = FastAPI()
    test_app.add_middleware(TraceIDMiddleware)
    test_app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(test_app)

    @test_app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    @test_app.get("/not-found")
    async def raise_not_found() -> None:
        raise NotFoundError("Widget")

    @test_app.get("/scope-violation")
    async def raise_scope() -> None:
        raise ScopeViolationError(
            expected_user_id=uuid.uuid4(),
            expected_knowledge_base_id=uuid.uuid4(),
        )

    @test_app.get("/auth-error")
    async def raise_auth() -> None:
        raise AuthenticationError("Token expired")

    @test_app.get("/invariant")
    async def raise_invariant() -> None:
        raise InvariantViolationError("Bad state")

    @test_app.get("/boom")
    async def raise_runtime() -> None:
        raise RuntimeError("Unexpected failure")

    return test_app


class TestTraceIDMiddleware:
    def test_response_has_x_trace_id_header(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/ok")
        assert "x-trace-id" in response.headers

    def test_trace_id_is_a_valid_uuid(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/ok")
        uuid.UUID(response.headers["x-trace-id"])

    def test_each_request_gets_a_unique_trace_id(self) -> None:
        with TestClient(_make_app()) as client:
            r1 = client.get("/ok")
            r2 = client.get("/ok")
        assert r1.headers["x-trace-id"] != r2.headers["x-trace-id"]

    def test_error_response_header_matches_body_trace_id(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/not-found")
        assert response.headers["x-trace-id"] == response.json()["trace_id"]


class TestExceptionHandlers:
    def test_not_found_error_returns_404(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/not-found")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_scope_violation_returns_404_not_403(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/scope-violation")
        assert response.status_code == 404

    def test_scope_violation_detail_is_generic(self) -> None:
        """The actual violation reason must not be revealed to the caller."""
        with TestClient(_make_app()) as client:
            response = client.get("/scope-violation")
        assert response.json()["detail"] == "Not found"

    def test_authentication_error_returns_401_with_www_authenticate(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/auth-error")
        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "Bearer"

    def test_invariant_violation_returns_422(self) -> None:
        with TestClient(_make_app()) as client:
            response = client.get("/invariant")
        assert response.status_code == 422

    def test_unhandled_exception_returns_500(self) -> None:
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            response = client.get("/boom")
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal server error"

    def test_every_error_response_body_contains_trace_id(self) -> None:
        endpoints = ["/not-found", "/scope-violation", "/auth-error", "/invariant"]
        with TestClient(_make_app()) as client:
            for endpoint in endpoints:
                body = client.get(endpoint).json()
                assert "trace_id" in body, f"{endpoint} response missing trace_id"
                uuid.UUID(body["trace_id"])


class TestRequestLoggingMiddleware:
    def test_logger_receives_standard_request_fields(self) -> None:
        with patch("app.api.middleware.logging.logger") as mock_logger:
            with TestClient(_make_app()) as client:
                client.get("/ok")
            mock_logger.info.assert_called_once()
            call = mock_logger.info.call_args
            assert call.kwargs.get("method") == "GET"
            assert call.kwargs.get("path") == "/ok"
            assert "status_code" in call.kwargs
            assert "duration_ms" in call.kwargs

    def test_authorization_header_value_is_never_logged(self) -> None:
        sensitive_value = "do-not-appear-in-any-log-output"
        with patch("app.api.middleware.logging.logger") as mock_logger:
            with TestClient(_make_app()) as client:
                client.get("/ok", headers={"Authorization": f"Bearer {sensitive_value}"})
            all_logged = str(mock_logger.info.call_args_list)
        assert sensitive_value not in all_logged


class TestCORSMiddleware:
    def _cors_app(self) -> FastAPI:
        cors_app = FastAPI()
        cors_app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @cors_app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"pong": True}

        return cors_app

    def test_allowed_origin_receives_cors_header(self) -> None:
        with TestClient(self._cors_app()) as client:
            response = client.get("/ping", headers={"Origin": "http://localhost:5173"})
        assert "access-control-allow-origin" in response.headers

    def test_disallowed_origin_does_not_receive_cors_header(self) -> None:
        with TestClient(self._cors_app()) as client:
            response = client.get("/ping", headers={"Origin": "http://evil.example.com"})
        assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"

    def test_a_browser_on_another_origin_can_read_the_trace_header(self) -> None:
        """Setting a header and exposing it are separate things.

        A browser hands script only a few headers by default, so a trace id echoed on
        every response is still unreadable from another origin unless it is named here.
        A frontend served through a development proxy is same-origin and never notices,
        which means the failure appears first in production and takes the identifier out
        of the errors somebody is trying to trace.
        """
        cors_app = FastAPI()
        cors_app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Trace-ID"],
        )
        cors_app.add_middleware(TraceIDMiddleware)

        @cors_app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"pong": True}

        with TestClient(cors_app) as client:
            response = client.get("/ping", headers={"Origin": "http://localhost:5173"})

        exposed = response.headers.get("access-control-expose-headers", "")
        assert "X-Trace-ID" in exposed
        assert response.headers.get("X-Trace-ID")

    def test_the_application_itself_exposes_the_trace_header(self) -> None:
        """The check above proves the setting works; this proves the real app carries it."""
        from app.main import app as real_app  # noqa: PLC0415

        cors = next(m for m in real_app.user_middleware if m.cls is CORSMiddleware)

        assert "X-Trace-ID" in (cors.kwargs.get("expose_headers") or [])
