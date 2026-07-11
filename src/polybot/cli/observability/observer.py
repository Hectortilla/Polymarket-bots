"""Observer protocol and fail-open helpers."""

from __future__ import annotations

from typing import Protocol

from polybot.cli.observability.events import RuntimeEvent
from polybot.framework.config import BotConfig


class RuntimeObserver(Protocol):
    async def start(self, config: BotConfig) -> None: ...

    def emit(self, event: RuntimeEvent) -> None: ...

    async def stop(self) -> None: ...


class NullRuntimeObserver:
    async def start(self, config: BotConfig) -> None:
        return None

    def emit(self, event: RuntimeEvent) -> None:
        return None

    async def stop(self) -> None:
        return None


async def start_observer(observer: RuntimeObserver, config: BotConfig) -> None:
    try:
        await observer.start(config)
    except Exception:
        return None


def emit_observer(observer: RuntimeObserver, event: RuntimeEvent) -> None:
    try:
        observer.emit(event)
    except Exception:
        return None


async def stop_observer(observer: RuntimeObserver) -> None:
    try:
        await observer.stop()
    except Exception:
        return None
