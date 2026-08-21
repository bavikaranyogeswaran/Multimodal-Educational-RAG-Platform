"""Structured log writer and database recorder for model invocations.

Each call emits a structlog event and adds a row to model_invocations. Both writes
happen in the same call so either form of observability can reconstruct what happened.
The trace_id is included so the invocation row can be joined with request-level logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.observability.context import TraceContext
from app.infrastructure.database.models.model_invocation import ModelInvocationModel

_log = structlog.get_logger(__name__)


async def write_model_invocation(
    *,
    session: AsyncSession,
    model_id: str,
    task: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int | None,
    used_fallback: bool = False,
    cache_hit: bool = False,
) -> None:
    trace_id: str | None = TraceContext.get().get("trace_id")
    _log.info(
        "model_invocation",
        model_id=model_id,
        task=task,
        provider=provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        used_fallback=used_fallback,
        cache_hit=cache_hit,
        trace_id=trace_id,
    )
    session.add(
        ModelInvocationModel(
            id=uuid.uuid4(),
            trace_id=trace_id,
            task=task,
            provider=provider,
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            used_fallback=used_fallback,
            cache_hit=cache_hit,
            created_at=datetime.now(UTC),
        )
    )
