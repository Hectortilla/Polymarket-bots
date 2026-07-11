from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from polymarket import AsyncPublicClient, RequestRejectedError

from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.normalization import normalize_market
from bots.polymarket.types import Market


class GammaClient:
    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None

    async def find_by_slug(self, slug: str) -> Market | None:
        if not slug.strip():
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "market slug must not be empty",
            )
        try:
            source = await self._client.get_market(slug=slug)
        except RequestRejectedError as error:
            if error.status == 404:
                return None
            raise
        return normalize_market(source)

    async def find_many(self, slugs: Iterable[str]) -> tuple[Market | None, ...]:
        return tuple(await asyncio.gather(*(self.find_by_slug(slug) for slug in slugs)))

    async def wait_for_slug(
        self,
        slug: str,
        *,
        retry_delay_s: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> Market:
        if retry_delay_s <= 0:
            raise ValueError("retry delay must be positive")
        while True:
            market = await self.find_by_slug(slug)
            if market is not None:
                return market
            await sleep(retry_delay_s)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.close()
