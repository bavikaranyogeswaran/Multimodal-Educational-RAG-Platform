"""Stage timer for measuring named processing stages."""

from __future__ import annotations

import time
from types import TracebackType


class StageTimer:
    """Context manager that measures the wall-clock duration of a named stage.

    Intended for use with the 17 §62 pipeline stages. Elapsed time is only
    readable after the context exits; calling `elapsed_ms()` before exit raises
    so callers get an immediate error rather than a silent zero.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._start: float = 0.0
        self._end: float = 0.0

    def __enter__(self) -> StageTimer:
        self._start = time.monotonic()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._end = time.monotonic()

    def elapsed_ms(self) -> int:
        if self._end == 0.0:
            raise RuntimeError(f"StageTimer '{self.name}' has not completed yet")
        return int((self._end - self._start) * 1000)
