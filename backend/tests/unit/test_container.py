"""Container and wiring tests.

Verifies that:
  1. build_container constructs a Container without raising
  2. Slots that have been wired hold a real adapter
  3. Slots that have not are _Unimplemented stubs that crash loudly on attribute access
  4. The container is stored on app.state after the lifespan runs

The point of the third check is that a missing wire-up fails at the first use with the
port's name in the message, rather than surfacing later as an opaque AttributeError.
Slots move from the third group to the second as phases land, so this test is expected
to be edited — but it is edited by deleting a name from one list and adding it to the
other, which is a change somebody has to make deliberately.
"""

from __future__ import annotations

import pytest

from app.configuration.container import Container
from app.configuration.settings import Settings
from app.configuration.wire import build_container

# Slots with a real adapter behind them, and an attribute each that proves it.
_WIRED = [
    ("model_gateway", "generate"),
    ("pdf_parser", "parse"),
]

# Slots still awaiting the phase that builds them.
_UNWIRED = [
    ("knowledge_base_repository", "get", "KnowledgeBaseRepository"),
    ("storage", "put", "StoragePort"),
    ("ocr", "extract_text", "OcrPort"),
    ("graph", "neighbors", "GraphPort"),
    ("cache", "get", "CacheStore"),
]


def test_build_container_returns_a_container() -> None:
    container = build_container(Settings())

    assert isinstance(container, Container)


@pytest.mark.parametrize(("slot", "attribute"), _WIRED)
def test_wired_slots_hold_a_real_adapter(slot: str, attribute: str) -> None:
    container = build_container(Settings())

    assert callable(getattr(getattr(container, slot), attribute))


@pytest.mark.parametrize(("slot", "attribute", "port_name"), _UNWIRED)
def test_unwired_slots_name_themselves_when_used(
    slot: str, attribute: str, port_name: str
) -> None:
    container = build_container(Settings())

    with pytest.raises(NotImplementedError, match=port_name):
        _ = getattr(getattr(container, slot), attribute)


async def test_lifespan_stores_container_on_app_state() -> None:
    from app.main import app

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.container, Container)
