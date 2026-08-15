"""FastAPI dependency that exposes the DI container to route handlers."""

from __future__ import annotations

from fastapi import Request

from app.configuration.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]
