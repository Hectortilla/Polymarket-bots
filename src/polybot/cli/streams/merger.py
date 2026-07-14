"""Lossless wallet and resolution merging with freshness-preserving books."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.types import MarketTradeHint

from .contracts import (
    BookStreamEvent,
    MarketHintStreamEvent,
    ResolutionStreamEvent,
    StreamCompleted,
    StreamEvent,
    StreamFailure,
    StreamKind,
    StreamSource,
    WalletStreamEvent,
)
from .telemetry import StreamTelemetry

if TYPE_CHECKING:
    from polybot.framework.events.books import BookSnapshot


@dataclass(frozen=True, slots=True)
class _BookMarker:
    token_id: str


@dataclass(frozen=True, slots=True)
class _MarketHintMarker:
    condition_id: str


QueuedItem = (
    BookStreamEvent
    | WalletStreamEvent
    | ResolutionStreamEvent
    | _MarketHintMarker
    | _BookMarker
    | StreamFailure
    | StreamCompleted
)


class StreamMerger:
    """Own source tasks and close every source when iteration ends."""

    def __init__(
        self,
        streams: tuple[tuple[StreamKind, StreamSource], ...],
        telemetry: StreamTelemetry | None,
    ) -> None:
        self._streams = streams
        self._telemetry = telemetry
        self._queue: asyncio.Queue[QueuedItem] = asyncio.Queue()
        self._pending_books: dict[str, BookSnapshot] = {}
        self._pending_market_hints: dict[str, MarketTradeHint] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._completed = 0
        self._started = False
        self._closed = False
        self._primary_stream_count = sum(
            kind is not StreamKind.RESOLUTION for kind, _ in streams
        )
        self._resolution_only = self._primary_stream_count == 0
        self._resolution_completed = 0

    def __aiter__(self) -> StreamMerger:
        if not self._started:
            self._tasks = [
                asyncio.create_task(self._consume_stream(kind, stream))
                for kind, stream in self._streams
            ]
            self._started = True
        return self

    async def __anext__(self) -> StreamEvent:
        if self._closed:
            raise StopAsyncIteration
        self.__aiter__()
        while self._completed < self._primary_stream_count or (
            self._resolution_only and self._resolution_completed == 0
        ):
            item = await self._queue.get()
            if self._telemetry is not None and not isinstance(
                item, (StreamFailure, StreamCompleted)
            ):
                self._telemetry.dequeued()
            if isinstance(item, StreamCompleted):
                if item.kind is not StreamKind.RESOLUTION:
                    self._completed += 1
                elif self._resolution_only:
                    self._resolution_completed += 1
                continue
            if isinstance(item, StreamFailure):
                await self.aclose()
                raise item.error
            if isinstance(item, _BookMarker):
                return BookStreamEvent(
                    StreamKind.BOOK,
                    self._pending_books.pop(item.token_id),
                )
            if isinstance(item, _MarketHintMarker):
                return MarketHintStreamEvent(
                    StreamKind.MARKET_HINT,
                    self._pending_market_hints.pop(item.condition_id),
                )
            return item
        await self.aclose()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for _, stream in self._streams:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        self._tasks.clear()
        self._streams = ()
        if self._telemetry is not None:
            self._telemetry.reset_queue_depth()

    async def _consume_stream(self, kind: StreamKind, stream: StreamSource) -> None:
        try:
            async for event in stream:
                if isinstance(event, MarketResolutionEvent):
                    await self._queue.put(
                        ResolutionStreamEvent(StreamKind.RESOLUTION, event)
                    )
                    if self._telemetry is not None:
                        self._telemetry.enqueued()
                elif isinstance(event, MarketTradeHint):
                    self._enqueue_market_hint(event)
                elif kind is StreamKind.BOOK:
                    self._enqueue_book(event)
                elif kind is StreamKind.WALLET:
                    await self._queue.put(WalletStreamEvent(kind, event))
                    if self._telemetry is not None:
                        self._telemetry.enqueued()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self._queue.put(StreamFailure(error))
        finally:
            await self._queue.put(StreamCompleted(kind))

    def _enqueue_book(self, event: BookSnapshot) -> None:
        token_id = getattr(event, "token_id", None)
        if not isinstance(token_id, str):
            self._queue.put_nowait(BookStreamEvent(StreamKind.BOOK, event))
            if self._telemetry is not None:
                self._telemetry.enqueued()
            return
        if self._telemetry is not None:
            self._telemetry.book_received()
        if token_id in self._pending_books:
            self._pending_books[token_id] = event
            if self._telemetry is not None:
                self._telemetry.book_dropped()
            return
        self._pending_books[token_id] = event
        self._queue.put_nowait(_BookMarker(token_id))
        if self._telemetry is not None:
            self._telemetry.enqueued()

    def _enqueue_market_hint(self, event: MarketTradeHint) -> None:
        if event.condition_id in self._pending_market_hints:
            self._pending_market_hints[event.condition_id] = event
            return
        self._pending_market_hints[event.condition_id] = event
        self._queue.put_nowait(_MarketHintMarker(event.condition_id))
        if self._telemetry is not None:
            self._telemetry.enqueued()


def merge_streams(
    streams: tuple[tuple[StreamKind, StreamSource], ...],
    *,
    telemetry: StreamTelemetry | None = None,
) -> StreamMerger:
    return StreamMerger(streams, telemetry)
