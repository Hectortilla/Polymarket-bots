from __future__ import annotations

from collections.abc import Callable, Iterable
from http import HTTPStatus

from polymarket import AsyncPublicClient, PolymarketError, RequestRejectedError

from polybot.framework.clock import system_now_ms
from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.client_lifecycle import (
    PublicClientLease,
)
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.normalization.book import normalize_book
from polybot.polymarket.markets import (
    Market,
    index_markets_by_token,
)


class ClobClient:
    def __init__(
        self,
        client: AsyncPublicClient | None = None,
        *,
        markets: Iterable[Market] = (),
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client_lease = PublicClientLease.acquire(client)
        self._client = self._client_lease.client
        self._now_ms = now_ms or system_now_ms
        self._market_by_token: dict[str, Market] = {}
        self.set_markets(markets)

    def set_markets(self, markets: Iterable[Market]) -> None:
        self._market_by_token = index_markets_by_token(markets)

    def add_market(self, market: Market) -> None:
        """Add metadata for a wallet-discovered market without dropping others."""
        self._market_by_token = index_markets_by_token(
            (*self._market_by_token.values(), market)
        )

    def has_market_slug(self, slug: str) -> bool:
        return any(candidate.slug == slug for candidate in self._market_by_token.values())

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
            raise MarketDataTransportError("CLOB order-book lookup failed") from error
        except PolymarketError as error:
            raise MarketDataTransportError("CLOB order-book lookup failed") from error
        market = self._market_by_token.get(token_id)
        return normalize_book(
            token_id=source.token_id,
            bids=source.bids,
            asks=source.asks,
            received_at_ms=self._now_ms(),
            condition_id=source.market,
            market_slug=market.slug if market else None,
            outcome=market.outcome_label_for_token(token_id) if market else None,
            expected_token_id=token_id,
            expected_condition_id=market.condition_id if market else None,
        )

    async def close(self) -> None:
        await self._client_lease.close()
