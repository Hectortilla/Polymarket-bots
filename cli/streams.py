"""Typed stream construction and multiplexing."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from bots.framework.events.books import BookSnapshot
    from bots.framework.events.wallet_trades import WalletTradeEvent
    from bots.polymarket.types import Market
    from bots.polymarket.wallet_activity.stream import WalletActivityStream
    from bots.polymarket.ws_market import MarketStream


class StreamKind(StrEnum):
    BOOK = "book"
    WALLET = "wallet"


@dataclass(frozen=True, slots=True)
class BookStreamEvent:
    kind: Literal[StreamKind.BOOK]
    event: BookSnapshot


@dataclass(frozen=True, slots=True)
class WalletStreamEvent:
    kind: Literal[StreamKind.WALLET]
    event: WalletTradeEvent


StreamEvent = BookStreamEvent | WalletStreamEvent


@dataclass(frozen=True, slots=True)
class StreamFailure:
    error: BaseException


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    pass


async def merge_streams(
    streams: tuple[
        tuple[StreamKind, AsyncIterator[BookSnapshot | WalletTradeEvent]], ...
    ],
) -> AsyncIterator[StreamEvent]:
    queue: asyncio.Queue[StreamEvent | StreamFailure | StreamCompleted] = asyncio.Queue()

    async def enqueue_stream_events(
        stream_kind: StreamKind,
        stream: AsyncIterator[BookSnapshot | WalletTradeEvent],
    ) -> None:
        try:
            async for event in stream:
                if stream_kind is StreamKind.BOOK:
                    await queue.put(BookStreamEvent(stream_kind, event))
                else:
                    await queue.put(WalletStreamEvent(stream_kind, event))
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
            if isinstance(item, StreamCompleted):
                completed += 1
            elif isinstance(item, StreamFailure):
                raise item.error
            else:
                yield item
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def build_streams(
    market_stream: MarketStream,
    *,
    wallet_stream: WalletActivityStream,
    markets: Iterable[Market],
    wallet_addresses: frozenset[str],
) -> tuple[
    tuple[StreamKind, AsyncIterator[BookSnapshot | WalletTradeEvent]], ...
]:
    streams: list[
        tuple[StreamKind, AsyncIterator[BookSnapshot | WalletTradeEvent]]
    ] = []
    from bots.polymarket.types import market_token_ids

    token_ids = {
        token_id for market in markets for token_id in market_token_ids(market)
    }
    if token_ids:
        streams.append((StreamKind.BOOK, market_stream.books(token_ids)))
    if wallet_addresses:
        streams.append((StreamKind.WALLET, wallet_stream.trades(wallet_addresses)))
    return tuple(streams)
