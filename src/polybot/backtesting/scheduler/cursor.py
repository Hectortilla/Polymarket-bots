"""Bounded asynchronous access to blocking archive event iteration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Event

from polybot.recording.contracts.records import RecordedEvent


REPLAY_QUEUE_POLL_INTERVAL_SECONDS = 0.1


REPLAY_EVENT_QUEUE_CAPACITY = 256


@dataclass(frozen=True, slots=True)
class _ReplayFailure:
    error: BaseException


class _ReplayEnd:
    pass


class ReplayCursor:
    """Bounded async handoff from blocking SQLite iteration."""

    def __init__(
        self,
        events: Iterator[RecordedEvent],
        *,
        after_sequence: int = 0,
        queue_capacity: int = REPLAY_EVENT_QUEUE_CAPACITY,
    ) -> None:
        self._events = events
        self._after_sequence = after_sequence
        self._next: RecordedEvent | None = None
        self._finished = False
        self._queue: asyncio.Queue[RecordedEvent | _ReplayFailure | _ReplayEnd] = (
            asyncio.Queue(maxsize=queue_capacity)
        )
        self._stop = Event()
        self._producer: asyncio.Task[None] | None = None

    async def peek(self) -> RecordedEvent | None:
        self._ensure_started()
        if self._next is None and not self._finished:
            item = await self._queue.get()
            if isinstance(item, _ReplayFailure):
                raise item.error
            if isinstance(item, _ReplayEnd):
                self._finished = True
            else:
                self._next = item
        return self._next

    async def pop(self) -> RecordedEvent | None:
        event = await self.peek()
        self._next = None
        return event

    async def aclose(self) -> None:
        self._stop.set()
        while not self._queue.empty():
            self._queue.get_nowait()
        if self._producer is not None:
            await self._producer
            self._producer = None

    def _ensure_started(self) -> None:
        if self._producer is None:
            self._producer = asyncio.create_task(
                asyncio.to_thread(self._produce, asyncio.get_running_loop())
            )

    def _produce(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            for event in self._events:
                if self._stop.is_set():
                    break
                if event.sequence > self._after_sequence and not self._put(loop, event):
                    break
        except BaseException as error:
            self._put(loop, _ReplayFailure(error))
        finally:
            self._put(loop, _ReplayEnd())

    def _put(
        self,
        loop: asyncio.AbstractEventLoop,
        item: RecordedEvent | _ReplayFailure | _ReplayEnd,
    ) -> bool:
        future = asyncio.run_coroutine_threadsafe(self._queue.put(item), loop)
        while not self._stop.is_set():
            try:
                future.result(timeout=REPLAY_QUEUE_POLL_INTERVAL_SECONDS)
                return True
            except FutureTimeoutError:
                continue
        future.cancel()
        return False
