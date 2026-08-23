"""Fail-open runtime observer for web-visible durable progress."""

import asyncio
from uuid import UUID

from polybot.cli.observability.events import (
    RuntimeEvent,
    StreamHealth,
)
from polybot.framework.config.models import BotConfig

from .contracts import DurableEvent
from .projection import (
    project_runtime_event_to_durable,
    project_terminal_stream_health,
)
from .writer import RunEventWriter


MAX_PENDING_EVENTS = 256


class WebRuntimeObserver:
    def __init__(
        self,
        run_id: UUID,
        event_writer: RunEventWriter,
        *,
        max_pending_events: int = MAX_PENDING_EVENTS,
    ) -> None:
        self._run_id = run_id
        self._event_writer = event_writer
        self._pending: asyncio.Queue[DurableEvent | None] = asyncio.Queue(
            maxsize=max_pending_events
        )
        self._writer: asyncio.Task[None] | None = None
        self._latest_stream_health: StreamHealth | None = None

    async def start(self, config: BotConfig) -> None:
        self._writer = asyncio.create_task(self._write_events())

    def emit(self, event: RuntimeEvent) -> None:
        if self._writer is None:
            return
        if isinstance(event, StreamHealth):
            self._latest_stream_health = event
            return
        for projected in project_runtime_event_to_durable(self._run_id, event):
            try:
                self._pending.put_nowait(projected)
            except asyncio.QueueFull:
                # Synchronous paper execution never blocks on bounded telemetry.
                return

    async def stop(self) -> None:
        if self._writer is None:
            return
        if self._latest_stream_health is not None:
            await self._pending.put(
                project_terminal_stream_health(
                    self._run_id,
                    self._latest_stream_health,
                )
            )
            self._latest_stream_health = None
        # The sentinel is queued after every accepted event so graceful stop
        # drains committed progress and final health before terminal lifecycle.
        await self._pending.put(None)
        await self._writer
        self._writer = None

    async def _write_events(self) -> None:
        while True:
            event = await self._pending.get()
            if event is None:
                return
            try:
                await self._event_writer.append(event)
            except Exception:
                # Observability must never change paper execution.
                continue
