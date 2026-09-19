"""One immutable pending live frame per authorized viewer."""

import asyncio
from dataclasses import dataclass

from api.events.live.clock import ShardClock


@dataclass(frozen=True, slots=True)
class LiveFrame:
    data: bytes
    deadline_us: int
    clock: ShardClock
    clock_epoch: int

    def fresh(self) -> bool:
        return self.clock.epoch == self.clock_epoch and self.clock.fresh(
            self.deadline_us
        )


class ViewerMailbox:
    def __init__(self) -> None:
        self._changed = asyncio.Event()
        self._live: LiveFrame | None = None
        self._durable_wake = False
        self._closed = False
        self._terminal = False

    def offer_live(self, frame: LiveFrame) -> None:
        if not self._closed and not self._terminal:
            self._live = frame
            self._changed.set()

    def offer_durable_wake(self) -> None:
        if not self._closed:
            self._durable_wake = True
            self._changed.set()

    def discard_live(self) -> None:
        self._live = None

    def terminal(self) -> None:
        self._terminal = True
        self.discard_live()
        self.offer_durable_wake()

    def close(self) -> None:
        self._closed = True
        self.discard_live()
        self._changed.set()

    async def next(self) -> tuple[LiveFrame | None, bool, bool]:
        await self._changed.wait()
        live, wake, closed = self._live, self._durable_wake, self._closed
        self._live = None
        self._durable_wake = False
        if not closed:
            self._changed.clear()
        return (live if live is not None and live.fresh() else None), wake, closed
