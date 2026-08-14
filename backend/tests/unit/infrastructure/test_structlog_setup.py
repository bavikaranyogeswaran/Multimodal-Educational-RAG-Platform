"""Unit tests for the structlog pipeline components.

Tests target the redaction processor directly rather than the full pipeline so
they do not depend on structlog being configured and do not produce log output.
"""

from __future__ import annotations

from app.configuration.settings import ObservabilitySettings
from app.infrastructure.observability.structlog_setup import _make_redaction_processor

_REDACTED = "[REDACTED]"


def _obs(
    *,
    log_prompts: bool = False,
    log_document_text: bool = False,
    log_model_outputs: bool = False,
) -> ObservabilitySettings:
    return ObservabilitySettings(
        log_prompts=log_prompts,
        log_document_text=log_document_text,
        log_model_outputs=log_model_outputs,
    )


class TestRedactionProcessor:
    # --- prompt -----------------------------------------------------------------

    def test_prompt_is_redacted_by_default_in_non_production(self) -> None:
        proc = _make_redaction_processor(_obs(log_prompts=False), is_production=False)
        result = proc(None, "info", {"event": "e", "prompt": "sensitive"})
        assert result["prompt"] == _REDACTED

    def test_prompt_passes_through_when_flag_is_true_in_non_production(self) -> None:
        proc = _make_redaction_processor(_obs(log_prompts=True), is_production=False)
        result = proc(None, "info", {"event": "e", "prompt": "visible"})
        assert result["prompt"] == "visible"

    def test_prompt_is_always_redacted_in_production(self) -> None:
        proc = _make_redaction_processor(_obs(log_prompts=True), is_production=True)
        result = proc(None, "info", {"event": "e", "prompt": "should be masked"})
        assert result["prompt"] == _REDACTED

    # --- document_text ----------------------------------------------------------

    def test_document_text_is_redacted_by_default(self) -> None:
        proc = _make_redaction_processor(_obs(), is_production=False)
        result = proc(None, "info", {"event": "e", "document_text": "private"})
        assert result["document_text"] == _REDACTED

    def test_document_text_passes_when_flag_is_true(self) -> None:
        proc = _make_redaction_processor(_obs(log_document_text=True), is_production=False)
        result = proc(None, "info", {"event": "e", "document_text": "ok to log"})
        assert result["document_text"] == "ok to log"

    def test_document_text_always_redacted_in_production(self) -> None:
        proc = _make_redaction_processor(_obs(log_document_text=True), is_production=True)
        result = proc(None, "info", {"event": "e", "document_text": "private"})
        assert result["document_text"] == _REDACTED

    # --- model_output -----------------------------------------------------------

    def test_model_output_is_redacted_by_default(self) -> None:
        proc = _make_redaction_processor(_obs(), is_production=False)
        result = proc(None, "info", {"event": "e", "model_output": "response"})
        assert result["model_output"] == _REDACTED

    def test_model_output_passes_when_flag_is_true(self) -> None:
        proc = _make_redaction_processor(_obs(log_model_outputs=True), is_production=False)
        result = proc(None, "info", {"event": "e", "model_output": "ok"})
        assert result["model_output"] == "ok"

    def test_model_output_always_redacted_in_production(self) -> None:
        proc = _make_redaction_processor(_obs(log_model_outputs=True), is_production=True)
        result = proc(None, "info", {"event": "e", "model_output": "private"})
        assert result["model_output"] == _REDACTED

    # --- non-sensitive fields ---------------------------------------------------

    def test_non_sensitive_fields_are_never_modified(self) -> None:
        proc = _make_redaction_processor(_obs(), is_production=True)
        event = {"event": "request", "method": "GET", "trace_id": "abc"}
        result = proc(None, "info", dict(event))
        assert result == event

    def test_sensitive_key_absent_from_event_is_not_added(self) -> None:
        proc = _make_redaction_processor(_obs(), is_production=True)
        result = proc(None, "info", {"event": "e"})
        assert "prompt" not in result
        assert "document_text" not in result
        assert "model_output" not in result
