"""Observer protocol and fail-open helpers."""

from __future__ import annotations

from typing import Protocol

from polybot.cli.observability.events import RuntimeEvent
from polybot.framework.config.models import BotConfig


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


class RuntimeObserverGroup:
    """Fan runtime telemetry out to independent fail-open observers."""

    def __init__(self, *observers: RuntimeObserver) -> None:
        self._observers = list(observers)

    def add(self, observer: RuntimeObserver) -> None:
        self._observers.append(observer)

    async def start(self, config: BotConfig) -> None:
        for observer in self._observers:
            await start_observer_fail_open(observer, config)

    def emit(self, event: RuntimeEvent) -> None:
        for observer in self._observers:
            emit_observer_fail_open(observer, event)

    async def stop(self) -> None:
        for observer in reversed(self._observers):
            await stop_observer_fail_open(observer)


async def start_observer_fail_open(observer: RuntimeObserver, config: BotConfig) -> None:
    try:
        await observer.start(config)
    except Exception:
        return None


def emit_observer_fail_open(
    observer: RuntimeObserver,
    event: RuntimeEvent,
) -> None:
    try:
        observer.emit(event)
    except Exception:
        return None


async def stop_observer_fail_open(observer: RuntimeObserver) -> None:
    try:
        await observer.stop()
    except Exception:
        return None
