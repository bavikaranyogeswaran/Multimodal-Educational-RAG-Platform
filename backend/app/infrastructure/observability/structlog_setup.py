"""Structlog pipeline configuration.

Call `configure_structlog(settings)` once during application startup — in the
FastAPI lifespan, before any code that might log. Calling it again overwrites
the previous configuration so it is safe in tests.

Processors (in order):
  1. stdlib log level → `level` field
  2. ISO 8601 timestamp → `timestamp` field
  3. Trace ID + user ID from TraceContext → injected on every event
  4. PII redaction — strips `prompt`, `document_text`, `model_output` unless
     content logging is explicitly enabled AND the environment is not production
  5. Stack info renderer (no-op when not present)
  6. JSON renderer (production / json format) or ConsoleRenderer (development)
"""

from __future__ import annotations

import io
import logging
import sys
from typing import Any, TextIO

import structlog
from structlog.types import EventDict, Processor

from app.application.observability.context import TraceContext
from app.configuration.settings import Environment, ObservabilitySettings, Settings

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = ("prompt", "document_text", "model_output")


def _inject_trace_context(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    event_dict.update(TraceContext.get())
    return event_dict


def _make_redaction_processor(obs: ObservabilitySettings, *, is_production: bool) -> Processor:
    """Return a structlog processor that redacts PII based on settings.

    In production every sensitive field is redacted unconditionally. In other
    environments the per-field flag allows content to pass through for debugging.
    """
    allow_prompts = not is_production and obs.log_prompts
    allow_document_text = not is_production and obs.log_document_text
    allow_model_outputs = not is_production and obs.log_model_outputs

    def _processor(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
        if not allow_prompts and "prompt" in event_dict:
            event_dict["prompt"] = _REDACTED
        if not allow_document_text and "document_text" in event_dict:
            event_dict["document_text"] = _REDACTED
        if not allow_model_outputs and "model_output" in event_dict:
            event_dict["model_output"] = _REDACTED
        return event_dict

    return _processor


def configure_structlog(settings: Settings) -> None:
    """Configure structlog for the application lifetime.

    Must be called before the first log event is emitted.
    """
    obs = settings.observability
    is_production = settings.app.environment == Environment.PRODUCTION

    logging.basicConfig(
        level=getattr(logging, obs.log_level),
        format="%(message)s",
    )

    use_json = obs.log_format == "json" or is_production
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_trace_context,
            _make_redaction_processor(obs, is_production=is_production),
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(file=_utf8_stdout()),
        cache_logger_on_first_use=True,
    )


def _utf8_stdout() -> TextIO:
    """Standard output that can carry the text this application actually logs.

    A Windows console hands Python a cp1252 stream, and almost everything logged here
    comes off a real document: an em dash in a heading, an accent in an author's name, an
    arrow in a diagram label. Writing one raises `UnicodeEncodeError` from inside the
    logging call, which turns a line nobody would have read into a failure that takes its
    caller down — this was first seen killing a response mid-stream, where the log was
    reporting the very failure the student then never heard about.

    Characters the stream still cannot represent are replaced rather than raised on. A
    mangled character in a log line is a much smaller problem than an exception thrown
    from the one code path whose job is to record problems.
    """
    stream = sys.stdout
    if getattr(stream, "encoding", "").lower().replace("-", "") == "utf8":
        return stream
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
        return stream
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream
    return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)
