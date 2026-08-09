"""Container and wiring tests.

Verifies that:
  1. build_container constructs a Container without raising
  2. _Unimplemented stubs crash loudly on attribute access with a clear message
  3. The container is stored on app.state after the lifespan runs
"""

from __future__ import annotations

import pytest

from app.configuration.container import Container
from app.configuration.settings import Settings
from app.configuration.wire import build_container


def test_build_container_returns_a_container() -> None:
    container = build_container(Settings())

    assert isinstance(container, Container)


def test_every_slot_raises_not_implemented_on_access() -> None:
    container = build_container(Settings())

    # Spot-check a representative selection across both repository and adapter slots.
    with pytest.raises(NotImplementedError, match="KnowledgeBaseRepository"):
        _ = container.knowledge_base_repository.get

    with pytest.raises(NotImplementedError, match="StoragePort"):
        _ = container.storage.put

    with pytest.raises(NotImplementedError, match="ModelGatewayPort"):
        _ = container.model_gateway.generate


async def test_lifespan_stores_container_on_app_state() -> None:
    from app.main import app

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.container, Container)
