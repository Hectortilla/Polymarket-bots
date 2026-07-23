"""Gamma adapter for normalized recording metadata."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from polymarket import AsyncPublicClient, PolymarketError

from polybot.polymarket.client_lifecycle import close_owned_public_client
from polybot.polymarket.errors import MarketDataTransportError
from polybot.polymarket.gamma import _GammaMarketSourceClient, wait_for_market
from polybot.polymarket.markets import validate_requested_market_slug

from .contracts import RecordingMarket
from .normalization import normalize_recording_market


class RecordingMarketResolver:
    """Resolve replay metadata without returning official SDK models."""

    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None
        self._sources = _GammaMarketSourceClient(self._client)

    async def find_by_slug(self, slug: str) -> RecordingMarket | None:
        try:
            source = await self._sources.find_by_slug(slug)
        except (MarketDataTransportError, PolymarketError) as error:
            raise MarketDataTransportError(
                "Gamma recording-market lookup failed"
            ) from _recording_lookup_cause(error)
        if source is None:
            return None
        recording_market = normalize_recording_market(source)
        validate_requested_market_slug(recording_market.market, slug)
        return recording_market

    async def find_many(
        self,
        slugs: Iterable[str],
    ) -> tuple[RecordingMarket | None, ...]:
        try:
            sources = await self._sources.find_many(slugs)
        except (MarketDataTransportError, PolymarketError) as error:
            raise MarketDataTransportError(
                "Gamma recording-market lookup failed"
            ) from _recording_lookup_cause(error)
        return tuple(
            None if source is None else normalize_recording_market(source)
            for source in sources
        )

    async def wait_for_slug(
        self,
        slug: str,
        *,
        retry_delay_s: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> RecordingMarket:
        return await wait_for_market(
            self.find_by_slug,
            slug,
            retry_delay_s=retry_delay_s,
            sleep=sleep,
        )

    async def close(self) -> None:
        if self._owns_client:
            await close_owned_public_client(self._client)


def _recording_lookup_cause(error: BaseException) -> BaseException:
    if isinstance(error, MarketDataTransportError) and isinstance(
        error.__cause__, PolymarketError
    ):
        return error.__cause__
    return error
