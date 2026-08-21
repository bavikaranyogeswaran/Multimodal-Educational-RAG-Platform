"""Model warm-up at application startup.

Sends a minimal one-token request so the model server loads weights into memory
before the first real request arrives. A failed warm-up logs a warning and returns
rather than blocking the server from starting — the first real request may be slow,
but the server is still usable.
"""

from __future__ import annotations

import structlog

from app.domain.enums import ModelTask
from app.domain.models.entities import ModelRequest
from app.domain.ports.model_gateway import ModelGatewayPort

_log = structlog.get_logger(__name__)


async def warm_up_models(gateway: ModelGatewayPort) -> None:
    """Issue a one-token generation request to load configured models into memory."""
    request = ModelRequest(
        model_task=ModelTask.ANSWER_GENERATION,
        system_preamble="Warmup.",
        safety_rules=(),
        task_instructions="Warmup.",
        query="1",
        max_tokens=1,
        temperature=0.0,
    )
    try:
        await gateway.generate(request)
        _log.info("model_warmup.done", task=ModelTask.ANSWER_GENERATION.value)
    except Exception as exc:
        _log.warning(
            "model_warmup.failed",
            task=ModelTask.ANSWER_GENERATION.value,
            error=str(exc),
        )
