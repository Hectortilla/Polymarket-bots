"""Runtime clock contract shared by bots and execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import time_ns
from typing import Protocol


class ClockDataExhaustedError(RuntimeError):
    """Signal that a simulated clock cannot advance within available data."""


class Clock(Protocol):
    def now_ms(self) -> int: ...

    async def sleep(self, seconds: float) -> None: ...


def system_now_ms() -> int:
    """Return the current system wall-clock time in whole milliseconds."""
    return time_ns() // 1_000_000


def system_now_utc() -> datetime:
    """Return the current system wall-clock time as an aware UTC datetime."""
    return datetime.now(UTC)


class SystemClock:
    """Clock backed by system wall time and the asyncio event loop."""

    def now_ms(self) -> int:
        return system_now_ms()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
