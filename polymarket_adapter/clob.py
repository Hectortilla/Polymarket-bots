from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from http import HTTPStatus

from polymarket import AsyncPublicClient, RequestRejectedError

from bots.framework.events.books import BookSnapshot
from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.normalization.book import normalize_book
from bots.polymarket.types import Market, index_markets_by_token, outcome_label_for_token


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
        self._market_by_token: dict[str, Market] = {}
        self.set_markets(markets)

    def set_markets(self, markets: Iterable[Market]) -> None:
        self._market_by_token = index_markets_by_token(markets)

    async def latest(self, token_id: str) -> BookSnapshot | None:
        if not token_id.strip():
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "token ID must not be empty",
            )
        try:
            source = await self._client.get_order_book(token_id=token_id)
        except RequestRejectedError as error:
            if error.status == HTTPStatus.NOT_FOUND:
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
            outcome=outcome_label_for_token(market, token_id) if market else None,
            expected_token_id=token_id,
            expected_condition_id=market.condition_id if market else None,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()
