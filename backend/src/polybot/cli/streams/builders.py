"""Construction of the currently active CLI stream set."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.markets import Market
from polybot.polymarket.market_hints import MarketTradeHint

from .contracts import (
    BookGapStreamEvent,
    BookStreamEvent,
    MarketHintStreamEvent,
    ResolutionStreamEvent,
    StreamSourceSpec,
    StreamSource,
    WalletStreamEvent,
)
from .kinds import StreamKind

if TYPE_CHECKING:
    from polybot.polymarket.wallet_activity.stream import WalletActivityStream
    from polybot.polymarket.ws_market import MarketStream


def build_streams(
    market_stream: MarketStream,
    *,
    wallet_stream: WalletActivityStream,
    markets: Iterable[Market],
    wallet_enabled: bool,
    resolution_stream: AsyncIterator[MarketResolutionEvent] | None = None,
) -> tuple[StreamSourceSpec, ...]:
    streams: list[StreamSourceSpec] = []
    token_ids = {
        token_id for market in markets for token_id in market.token_ids
    }
    if token_ids:
        streams.append(
            StreamSourceSpec.primary(
                _market_events(market_stream.events(token_ids))
            )
        )
    if wallet_enabled:
        streams.append(StreamSourceSpec.primary(_wallet_events(wallet_stream.trades())))
    if resolution_stream is not None:
        streams.append(
            StreamSourceSpec.auxiliary(_resolution_events(resolution_stream))
        )
    return tuple(streams)


async def _market_events(
    events: AsyncIterator[
        BookSnapshot | BookGapEvent | MarketTradeHint | MarketResolutionEvent
    ],
) -> AsyncIterator[
    BookStreamEvent
    | BookGapStreamEvent
    | MarketHintStreamEvent
    | ResolutionStreamEvent
]:
    async for event in events:
        if isinstance(event, BookSnapshot):
            yield BookStreamEvent(StreamKind.BOOK, event)
        elif isinstance(event, BookGapEvent):
            yield BookGapStreamEvent(StreamKind.BOOK_GAP, event)
        elif isinstance(event, MarketTradeHint):
            yield MarketHintStreamEvent(StreamKind.MARKET_HINT, event)
        else:
            yield ResolutionStreamEvent(StreamKind.RESOLUTION, event)


async def _wallet_events(
    events: AsyncIterator[WalletTradeEvent],
) -> AsyncIterator[WalletStreamEvent]:
    async for event in events:
        yield WalletStreamEvent(StreamKind.WALLET, event)


async def _resolution_events(
    events: AsyncIterator[MarketResolutionEvent],
) -> AsyncIterator[ResolutionStreamEvent]:
    async for event in events:
        yield ResolutionStreamEvent(StreamKind.RESOLUTION, event)
