"""Typed stream construction and multiplexing."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from polybot.polymarket.types import MarketTradeHint

if TYPE_CHECKING:
    from polybot.framework.events.books import BookSnapshot
    from polybot.framework.events.wallet_trades import WalletTradeEvent
    from polybot.polymarket.types import Market
    from polybot.polymarket.wallet_activity.stream import WalletActivityStream
    from polybot.polymarket.ws_market import MarketStream


class StreamKind(StrEnum):
    BOOK = "book"
    WALLET = "wallet"
    MARKET_HINT = "market_hint"


@dataclass(frozen=True, slots=True)
class BookStreamEvent:
    kind: Literal[StreamKind.BOOK]
    event: BookSnapshot


@dataclass(frozen=True, slots=True)
class WalletStreamEvent:
    kind: Literal[StreamKind.WALLET]
    event: WalletTradeEvent


@dataclass(frozen=True, slots=True)
class MarketHintStreamEvent:
    kind: Literal[StreamKind.MARKET_HINT]
    event: MarketTradeHint


StreamEvent = BookStreamEvent | WalletStreamEvent | MarketHintStreamEvent


@dataclass(frozen=True, slots=True)
class StreamFailure:
    error: BaseException


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    pass


@dataclass(frozen=True, slots=True)
class _BookMarker:
    token_id: str


@dataclass(frozen=True, slots=True)
class _MarketHintMarker:
    condition_id: str


@dataclass(slots=True)
class StreamTelemetry:
    queue_depth: int = 0
    peak_queue_depth: int = 0
    book_received_count: int = 0
    book_dropped_count: int = 0

    def enqueued(self) -> None:
        self.queue_depth += 1
        self.peak_queue_depth = max(self.peak_queue_depth, self.queue_depth)

    def dequeued(self) -> None:
        self.queue_depth = max(0, self.queue_depth - 1)

    def book_received(self) -> None:
        self.book_received_count += 1

    def book_dropped(self) -> None:
        self.book_dropped_count += 1

    def reset_queue_depth(self) -> None:
        self.queue_depth = 0

    @property
    def book_drop_ratio(self) -> float:
        if self.book_received_count == 0:
            return 0.0
        return self.book_dropped_count / self.book_received_count


async def merge_streams(
    streams: tuple[
        tuple[StreamKind, AsyncIterator[BookSnapshot | WalletTradeEvent | MarketTradeHint]], ...
    ],
    *,
    telemetry: StreamTelemetry | None = None,
) -> AsyncIterator[StreamEvent]:
    queue: asyncio.Queue[
        BookStreamEvent
        | WalletStreamEvent
        | _BookMarker
        | _MarketHintMarker
        | StreamFailure
        | StreamCompleted
    ] = asyncio.Queue()
    pending_books: dict[str, BookSnapshot] = {}
    pending_market_hints: dict[str, MarketTradeHint] = {}

    def enqueue_book(event: BookSnapshot) -> None:
        token_id = getattr(event, "token_id", None)
        if not isinstance(token_id, str):
            queue.put_nowait(BookStreamEvent(StreamKind.BOOK, event))
            if telemetry is not None:
                telemetry.enqueued()
            return
        if telemetry is not None:
            telemetry.book_received()
        if token_id in pending_books:
            pending_books[token_id] = event
            if telemetry is not None:
                telemetry.book_dropped()
            return
        pending_books[token_id] = event
        queue.put_nowait(_BookMarker(token_id))
        if telemetry is not None:
            telemetry.enqueued()

    def enqueue_market_hint(event: MarketTradeHint) -> None:
        if event.condition_id in pending_market_hints:
            pending_market_hints[event.condition_id] = event
            return
        pending_market_hints[event.condition_id] = event
        queue.put_nowait(_MarketHintMarker(event.condition_id))
        if telemetry is not None:
            telemetry.enqueued()

    async def enqueue_stream_events(
        stream_kind: StreamKind,
        stream: AsyncIterator[BookSnapshot | WalletTradeEvent | MarketTradeHint],
    ) -> None:
        try:
            async for event in stream:
                if isinstance(event, MarketTradeHint):
                    enqueue_market_hint(event)
                elif stream_kind is StreamKind.BOOK:
                    enqueue_book(event)
                elif stream_kind is StreamKind.WALLET:
                    await queue.put(WalletStreamEvent(stream_kind, event))
                    if telemetry is not None:
                        telemetry.enqueued()
        except BaseException as error:
            await queue.put(StreamFailure(error))
        finally:
            await queue.put(StreamCompleted())

    tasks = [
        asyncio.create_task(enqueue_stream_events(stream_kind, stream))
        for stream_kind, stream in streams
    ]
    completed = 0
    try:
        while completed < len(tasks):
            item = await queue.get()
            if telemetry is not None and not isinstance(item, (StreamFailure, StreamCompleted)):
                telemetry.dequeued()
            if isinstance(item, StreamCompleted):
                completed += 1
            elif isinstance(item, StreamFailure):
                raise item.error
            elif isinstance(item, _BookMarker):
                yield BookStreamEvent(StreamKind.BOOK, pending_books.pop(item.token_id))
            elif isinstance(item, _MarketHintMarker):
                yield MarketHintStreamEvent(
                    StreamKind.MARKET_HINT,
                    pending_market_hints.pop(item.condition_id),
                )
            else:
                yield item
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if telemetry is not None:
            telemetry.reset_queue_depth()


def build_streams(
    market_stream: MarketStream,
    *,
    wallet_stream: WalletActivityStream,
    markets: Iterable[Market],
    wallet_enabled: bool,
) -> tuple[
        tuple[StreamKind, AsyncIterator[BookSnapshot | WalletTradeEvent | MarketTradeHint]], ...
]:
    streams: list[
        tuple[StreamKind, AsyncIterator[BookSnapshot | WalletTradeEvent | MarketTradeHint]]
    ] = []
    from polybot.polymarket.types import market_token_ids

    token_ids = {
        token_id for market in markets for token_id in market_token_ids(market)
    }
    if token_ids:
        stream = (
            market_stream.events(token_ids)
            if hasattr(market_stream, "events")
            else market_stream.books(token_ids)
        )
        streams.append((StreamKind.BOOK, stream))
    if wallet_enabled:
        streams.append((StreamKind.WALLET, wallet_stream.trades()))
    return tuple(streams)
