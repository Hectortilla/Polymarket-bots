"""Construction of the currently active CLI stream set."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import TYPE_CHECKING

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.polymarket.markets import Market

from .contracts import StreamKind, StreamSource

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
) -> tuple[tuple[StreamKind, StreamSource], ...]:
    streams: list[tuple[StreamKind, StreamSource]] = []
    token_ids = {
        token_id for market in markets for token_id in market.token_ids
    }
    if token_ids:
        streams.append((StreamKind.BOOK, market_stream.events(token_ids)))
    if wallet_enabled:
        streams.append((StreamKind.WALLET, wallet_stream.trades()))
    if resolution_stream is not None:
        streams.append((StreamKind.RESOLUTION, resolution_stream))
    return tuple(streams)
