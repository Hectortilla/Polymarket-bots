"""Runtime-observer adapter for paper-performance recording."""

from __future__ import annotations

from polybot.cli.observability.events import RuntimeEvent
from polybot.framework.config.models import BotConfig

from .recording import PaperPerformanceRecorder


class PaperPerformanceObserver:
    """Bridge runtime lifecycle events into a paper-performance recorder."""

    def __init__(self, recorder: PaperPerformanceRecorder) -> None:
        self._recorder = recorder

    async def start(self, config: BotConfig) -> None:
        del config
        await self._recorder.start()

    def emit(self, event: RuntimeEvent) -> None:
        self._recorder.emit(event)

    async def stop(self) -> None:
        await self._recorder.stop()
