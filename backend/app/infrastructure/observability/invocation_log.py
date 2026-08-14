"""Structured log writer for model invocations.

Phase 8 adds a database write on top of this; for now the log event is the
only record. The `trace_id` is included explicitly so the event can be
correlated with request logs even when structlog is not fully configured.
"""

from __future__ import annotations

import structlog

from app.application.observability.context import TraceContext

_log = structlog.get_logger(__name__)


def write_model_invocation(
    *,
    model_id: str,
    task: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
) -> None:
    _log.info(
        "model_invocation",
        model_id=model_id,
        task=task,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        trace_id=TraceContext.get()["trace_id"],
    )
