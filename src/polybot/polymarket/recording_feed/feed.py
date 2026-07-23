"""Official-SDK subscription owner for recording condition captures."""

from __future__ import annotations

from polymarket import AsyncPublicClient, PolymarketError
from polymarket.streams import MarketSpec

from polybot.polymarket.client_lifecycle import close_owned_public_client
from polybot.polymarket.errors import MarketDataTransportError
from polybot.polymarket.markets import Market

from .capture import MarketCapture


class MarketRecordingFeed:
    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None

    async def open_capture(
        self,
        market: Market,
        *,
        generation: int,
    ) -> MarketCapture:
        if generation < 0:
            raise ValueError("subscription generation must not be negative")
        try:
            handle = await self._client.subscribe(
                MarketSpec(
                    token_ids=market.token_ids,
                    custom_feature_enabled=True,
                )
            )
        except PolymarketError as error:
            raise MarketDataTransportError(
                "recording market subscription failed"
            ) from error
        return MarketCapture(handle, market=market, generation=generation)

    async def close(self) -> None:
        if self._owns_client:
            await close_owned_public_client(self._client)
