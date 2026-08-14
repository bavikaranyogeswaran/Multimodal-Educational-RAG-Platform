"""Unit tests for StageTimer."""

from __future__ import annotations

import time

import pytest

from app.application.observability.timer import StageTimer


class TestStageTimer:
    def test_elapsed_ms_returns_int(self) -> None:
        with StageTimer("s") as t:
            pass
        assert isinstance(t.elapsed_ms(), int)

    def test_elapsed_ms_is_non_negative(self) -> None:
        with StageTimer("s") as t:
            pass
        assert t.elapsed_ms() >= 0

    def test_measures_real_elapsed_time(self) -> None:
        with StageTimer("s") as t:
            time.sleep(0.02)
        assert t.elapsed_ms() >= 20

    def test_name_is_preserved(self) -> None:
        with StageTimer("my_stage") as t:
            pass
        assert t.name == "my_stage"

    def test_elapsed_ms_raises_before_context_exits(self) -> None:
        t = StageTimer("incomplete")
        with pytest.raises(RuntimeError, match="not completed"):
            t.elapsed_ms()

    def test_elapsed_ms_usable_inside_with_block_after_reassignment(self) -> None:
        """Timer reference captured from __enter__ must survive the with block."""
        timer = StageTimer("ref_test")
        with timer:
            pass
        assert timer.elapsed_ms() >= 0
