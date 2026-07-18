"""Virtual clock whose sleeps are driven by the replay scheduler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from polybot.framework.clock import ClockDataExhaustedError


AdvanceFn = Callable[[int], Awaitable[None]]


class ReplayClock:
    def __init__(self, start_at_ms: int, end_at_ms: int) -> None:
        if start_at_ms < 0 or end_at_ms < start_at_ms:
            raise ValueError("replay clock bounds are invalid")
        self._now_ms = start_at_ms
        self._end_at_ms = end_at_ms
        self._advance: AdvanceFn | None = None

    def now_ms(self) -> int:
        return self._now_ms

    @property
    def end_at_ms(self) -> int:
        return self._end_at_ms

    def set_advance_driver(self, advance: AdvanceFn) -> None:
        self._advance = advance

    def move_to(self, target_ms: int) -> None:
        if target_ms < self._now_ms:
            raise ValueError("replay time cannot move backwards")
        if target_ms > self._end_at_ms:
            raise ClockDataExhaustedError(
                "simulated latency extends beyond selected recording data"
            )
        self._now_ms = target_ms

    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("clock sleep must be nonnegative")
        target_ms = self._now_ms + round(seconds * 1_000)
        if target_ms > self._end_at_ms:
            raise ClockDataExhaustedError(
                "simulated latency extends beyond selected recording data"
            )
        if self._advance is None:
            self.move_to(target_ms)
            return
        await self._advance(target_ms)
        self.move_to(target_ms)
