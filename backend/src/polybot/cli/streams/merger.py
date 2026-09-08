"""Lossless wallet and resolution merging with freshness-preserving books."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from polybot.framework.coalescing import PendingByKey
from polybot.polymarket.market_hints import MarketTradeHint

from .contracts import (
    BookGapStreamEvent,
    BookStreamEvent,
    MarketHintStreamEvent,
    ResolutionStreamEvent,
    StreamCompleted,
    StreamCompletionRole,
    StreamEvent,
    StreamFailure,
    StreamSource,
    StreamSourceSpec,
    WalletStreamEvent,
)
from .kinds import StreamKind
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
    | BookGapStreamEvent
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
        streams: tuple[StreamSourceSpec, ...],
        telemetry: StreamTelemetry | None,
    ) -> None:
        self._streams = streams
        self._telemetry = telemetry
        self._queue: asyncio.Queue[QueuedItem] = asyncio.Queue()
        self._pending_books: PendingByKey[str, BookSnapshot] = PendingByKey()
        self._stale_book_marker_counts: dict[str, int] = {}
        self._pending_market_hints: PendingByKey[str, MarketTradeHint] = PendingByKey()
        self._tasks: list[asyncio.Task[None]] = []
        self._completed = 0
        self._started = False
        self._closed = False
        self._primary_stream_count = sum(
            stream.completion_role is StreamCompletionRole.PRIMARY
            for stream in streams
        )
        self._resolution_only = self._primary_stream_count == 0
        self._resolution_completed = 0

    def __aiter__(self) -> StreamMerger:
        if not self._started:
            self._tasks = [
                asyncio.create_task(self._consume_stream(stream))
                for stream in self._streams
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
                if item.completion_role is StreamCompletionRole.PRIMARY:
                    self._completed += 1
                elif self._resolution_only:
                    self._resolution_completed += 1
                continue
            if isinstance(item, StreamFailure):
                await self.aclose()
                raise item.error
            if isinstance(item, _BookMarker):
                stale_marker_count = self._stale_book_marker_counts.get(
                    item.token_id,
                    0,
                )
                if stale_marker_count:
                    if stale_marker_count == 1:
                        del self._stale_book_marker_counts[item.token_id]
                    else:
                        self._stale_book_marker_counts[item.token_id] = (
                            stale_marker_count - 1
                        )
                    continue
                if item.token_id not in self._pending_books:
                    continue
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
        close_operations = tuple(
            close()
            for stream_spec in self._streams
            if (close := getattr(stream_spec.source, "aclose", None)) is not None
        )
        if close_operations:
            await asyncio.gather(*close_operations, return_exceptions=True)
        self._tasks.clear()
        self._streams = ()
        if self._telemetry is not None:
            self._telemetry.reset_queue_depth()

    async def _consume_stream(self, stream_spec: StreamSourceSpec) -> None:
        try:
            async for event in stream_spec.source:
                if isinstance(event, BookStreamEvent):
                    self._enqueue_book(event.event)
                elif isinstance(event, BookGapStreamEvent):
                    self._discard_unsafe_books(event)
                    await self._queue.put(event)
                    if self._telemetry is not None:
                        self._telemetry.enqueued()
                elif isinstance(event, MarketHintStreamEvent):
                    self._enqueue_market_hint(event.event)
                else:
                    await self._queue.put(event)
                    if self._telemetry is not None:
                        self._telemetry.enqueued()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self._queue.put(StreamFailure(error))
        finally:
            await self._queue.put(
                StreamCompleted(stream_spec.completion_role)
            )

    def _enqueue_book(self, event: BookSnapshot) -> None:
        token_id = getattr(event, "token_id", None)
        if not isinstance(token_id, str):
            self._queue.put_nowait(BookStreamEvent(StreamKind.BOOK, event))
            if self._telemetry is not None:
                self._telemetry.enqueued()
            return
        if self._telemetry is not None:
            self._telemetry.book_received()
        if not self._pending_books.update(token_id, event):
            if self._telemetry is not None:
                self._telemetry.book_coalesced()
            return
        self._queue.put_nowait(_BookMarker(token_id))
        if self._telemetry is not None:
            self._telemetry.enqueued()

    def _enqueue_market_hint(self, event: MarketTradeHint) -> None:
        if not self._pending_market_hints.update(event.condition_id, event):
            return
        self._queue.put_nowait(_MarketHintMarker(event.condition_id))
        if self._telemetry is not None:
            self._telemetry.enqueued()

    def _discard_unsafe_books(self, event: BookGapStreamEvent) -> None:
        discarded_token_ids = self._pending_books.discard_matching_keys(
            lambda book: event.event.affects(book.condition_id)
        )
        # Queue markers cannot be removed when their pending books are discarded.
        # Count them so an old marker cannot publish a newer post-gap replacement.
        for token_id in discarded_token_ids:
            self._stale_book_marker_counts[token_id] = (
                self._stale_book_marker_counts.get(token_id, 0) + 1
            )


def merge_streams(
    streams: tuple[StreamSourceSpec, ...],
    *,
    telemetry: StreamTelemetry | None = None,
) -> StreamMerger:
    return StreamMerger(streams, telemetry)
