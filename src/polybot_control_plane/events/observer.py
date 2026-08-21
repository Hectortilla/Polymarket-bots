"""Fail-open runtime observer for web-visible durable progress."""

import asyncio
from uuid import UUID

from polybot.cli.observability.events import (
    RuntimeEvent,
)
from polybot.framework.config.models import BotConfig

from .contracts import DurableEvent, MAX_PENDING_EVENTS
from .projection import project_event
from .store import EventStore


class WebRuntimeObserver:
    def __init__(self, run_id: UUID, event_store: EventStore, *, max_pending_events: int = MAX_PENDING_EVENTS) -> None:
        self._run_id = run_id
        self._event_store = event_store
        self._pending: asyncio.Queue[DurableEvent | None] = asyncio.Queue(maxsize=max_pending_events)
        self._writer: asyncio.Task[None] | None = None

    async def start(self, config: BotConfig) -> None:
        self._writer = asyncio.create_task(self._write_events())

    def emit(self, event: RuntimeEvent) -> None:
        projected = project_event(self._run_id, event)
        if projected is None or self._writer is None:
            return
        try:
            self._pending.put_nowait(projected)
        except asyncio.QueueFull:
            return

    async def stop(self) -> None:
        if self._writer is None:
            return
        await self._pending.put(None)
        await self._writer
        self._writer = None

    async def _write_events(self) -> None:
        while True:
            event = await self._pending.get()
            if event is None:
                return
            try:
                await self._event_store.append(event)
            except Exception:
                # Observability must never change paper execution.
                continue
