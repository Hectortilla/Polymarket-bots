"""Monotonic observation time anchored to Unix time."""

from __future__ import annotations

import time
from collections.abc import Callable


class ObservationClock:
    """Provide nondecreasing epoch milliseconds without following wall-clock jumps."""

    def __init__(
        self,
        *,
        unix_time_ns: Callable[[], int] = time.time_ns,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._monotonic_ns = monotonic_ns
        self._unix_anchor_ns = unix_time_ns()
        self._monotonic_anchor_ns = monotonic_ns()
        self._floor_ms = 0

    def now_ms(self) -> int:
        elapsed_ns = self._monotonic_ns() - self._monotonic_anchor_ns
        observed_at_ms = (self._unix_anchor_ns + elapsed_ns) // 1_000_000
        self._floor_ms = max(self._floor_ms, observed_at_ms)
        return self._floor_ms

    def advance_to(self, observed_at_ms: int) -> None:
        """Keep a resumed archive monotonic across process clock anchors."""
        if observed_at_ms < 0:
            raise ValueError("observation clock floor must not be negative")
        self._floor_ms = max(self._floor_ms, observed_at_ms)
