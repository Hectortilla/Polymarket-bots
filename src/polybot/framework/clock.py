"""Runtime clock contract shared by bots and execution."""

from __future__ import annotations

import asyncio
from time import time_ns
from typing import Protocol


class ClockDataExhaustedError(RuntimeError):
    """Signal that a simulated clock cannot advance within available data."""


class Clock(Protocol):
    def now_ms(self) -> int: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Clock backed by system wall time and the asyncio event loop."""

    def now_ms(self) -> int:
        return time_ns() // 1_000_000

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
