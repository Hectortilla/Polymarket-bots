from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from polymarket import AsyncPublicClient, RequestRejectedError

from bots.framework.events.books import BookSnapshot
from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.normalization import normalize_book
from bots.polymarket.types import Market


class ClobClient:
    def __init__(
        self,
        client: AsyncPublicClient | None = None,
        *,
        markets: Iterable[Market] = (),
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None
        self._now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self._market_by_token = {
            token_id: market
            for market in markets
            for token_id in (market.yes_token_id, market.no_token_id)
        }

    async def latest(self, token_id: str) -> BookSnapshot | None:
        if not token_id.strip():
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "token ID must not be empty",
            )
        try:
            source = await self._client.get_order_book(token_id=token_id)
        except RequestRejectedError as error:
            if error.status == 404:
                return None
            raise
        market = self._market_by_token.get(token_id)
        return normalize_book(
            token_id=source.token_id,
            bids=source.bids,
            asks=source.asks,
            received_at_ms=self._now_ms(),
            condition_id=source.market,
            market_slug=market.slug if market else None,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()
