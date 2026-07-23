from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from http import HTTPStatus
from typing import Final, TypeVar
from urllib.parse import urlencode

from polymarket import AsyncPublicClient, PolymarketError, RequestRejectedError
from polymarket.models.gamma.market import Market as SdkMarket

from polybot.polymarket.client_lifecycle import close_owned_public_client
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.normalization.market import normalize_market
from polybot.polymarket.markets import Market, validate_requested_market_slug


GAMMA_MARKETS_PAGE_SIZE: Final = 100
GAMMA_MARKETS_MAX_SLUGS_PER_REQUEST: Final = GAMMA_MARKETS_PAGE_SIZE
GAMMA_MARKETS_QUERY_BUDGET: Final = 60_000
GAMMA_MARKETS_SLUG_QUERY_PARAMETER: Final = "slug"
GAMMA_MARKETS_PAGE_SIZE_QUERY_PARAMETER: Final = "limit"
MarketT = TypeVar("MarketT")


class _GammaMarketSourceClient:
    """Own raw official-SDK Gamma queries shared by normalized adapters."""

    def __init__(self, client: AsyncPublicClient) -> None:
        self._client = client

    async def find_by_slug(self, slug: str) -> SdkMarket | None:
        self._validate_slug(slug)
        try:
            return await self._client.get_market(slug=slug)
        except RequestRejectedError as error:
            if error.status == HTTPStatus.NOT_FOUND:
                return None
            raise MarketDataTransportError(
                "Gamma market lookup failed"
            ) from error
        except PolymarketError as error:
            raise MarketDataTransportError("Gamma market lookup failed") from error

    async def find_many(
        self,
        slugs: Iterable[str],
    ) -> tuple[SdkMarket | None, ...]:
        requested_slugs = tuple(slugs)
        for slug in requested_slugs:
            self._validate_slug(slug)
        unique_slugs = tuple(dict.fromkeys(requested_slugs))
        if not unique_slugs:
            return ()

        markets_by_slug: dict[str, SdkMarket] = {}
        await self._collect_market_sources(unique_slugs, markets_by_slug)
        unresolved_slugs = tuple(
            slug for slug in unique_slugs if slug not in markets_by_slug
        )
        if unresolved_slugs:
            await self._collect_market_sources(
                unresolved_slugs,
                markets_by_slug,
                closed=True,
            )
        return tuple(markets_by_slug.get(slug) for slug in requested_slugs)

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if not slug.strip():
            raise MarketDataError(
                MarketDataIssue.EMPTY_IDENTIFIER,
                "market slug must not be empty",
            )

    async def _collect_market_sources(
        self,
        slugs: Iterable[str],
        markets_by_slug: dict[str, SdkMarket],
        *,
        closed: bool | None = None,
    ) -> None:
        for slug_batch in _iter_slug_batches(slugs):
            requested_batch = frozenset(slug_batch)
            try:
                paginator = self._client.list_markets(
                    slug=slug_batch,
                    closed=closed,
                    page_size=GAMMA_MARKETS_PAGE_SIZE,
                )
                async for source in paginator.iter_items():
                    market = normalize_market(source)
                    if market.slug not in requested_batch:
                        raise MarketDataError(
                            MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                            "Gamma response contained an unrequested market slug",
                        )
                    previous = markets_by_slug.get(market.slug)
                    if previous is not None and normalize_market(previous) != market:
                        raise MarketDataError(
                            MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                            f"Gamma returned conflicting rows for slug: {market.slug}",
                        )
                    markets_by_slug[market.slug] = source
            except PolymarketError as error:
                raise MarketDataTransportError(
                    "Gamma market lookup failed"
                ) from error


class GammaClient:
    """Normalize Gamma metadata for market and execution-domain consumers."""

    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._client = client or AsyncPublicClient()
        self._owns_client = client is None
        self._sources = _GammaMarketSourceClient(self._client)

    async def find_by_slug(self, slug: str) -> Market | None:
        source = await self._sources.find_by_slug(slug)
        if source is None:
            return None
        market = normalize_market(source)
        validate_requested_market_slug(market, slug)
        return market

    async def find_many(self, slugs: Iterable[str]) -> tuple[Market | None, ...]:
        sources = await self._sources.find_many(slugs)
        return tuple(
            None if source is None else normalize_market(source) for source in sources
        )

    async def wait_for_slug(
        self,
        slug: str,
        *,
        retry_delay_s: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> Market:
        return await wait_for_market(
            self.find_by_slug,
            slug,
            retry_delay_s=retry_delay_s,
            sleep=sleep,
        )

    async def close(self) -> None:
        if self._owns_client:
            await close_owned_public_client(self._client)


def _iter_slug_batches(slugs: Iterable[str]) -> Iterable[tuple[str, ...]]:
    # Keep batches below httpx's 65,536-character URL query-component limit.
    current: list[str] = []
    current_query_length = _encoded_query_length(())
    for slug in slugs:
        slug_query_length = len(
            urlencode(((GAMMA_MARKETS_SLUG_QUERY_PARAMETER, slug),))
        )
        candidate_query_length = current_query_length + 1 + slug_query_length
        if current and (
            len(current) >= GAMMA_MARKETS_MAX_SLUGS_PER_REQUEST
            or candidate_query_length > GAMMA_MARKETS_QUERY_BUDGET
        ):
            yield tuple(current)
            current = []
            current_query_length = _encoded_query_length(())
            candidate_query_length = current_query_length + 1 + slug_query_length
        current.append(slug)
        current_query_length = candidate_query_length
    if current:
        yield tuple(current)


def _encoded_query_length(slugs: Iterable[str]) -> int:
    params = [(GAMMA_MARKETS_SLUG_QUERY_PARAMETER, slug) for slug in slugs]
    params.append(
        (GAMMA_MARKETS_PAGE_SIZE_QUERY_PARAMETER, str(GAMMA_MARKETS_PAGE_SIZE))
    )
    return len(urlencode(params))


async def wait_for_market(
    find_by_slug: Callable[[str], Awaitable[MarketT | None]],
    slug: str,
    *,
    retry_delay_s: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> MarketT:
    if retry_delay_s <= 0:
        raise ValueError("retry delay must be positive")
    while True:
        market = await find_by_slug(slug)
        if market is not None:
            return market
        await sleep(retry_delay_s)
