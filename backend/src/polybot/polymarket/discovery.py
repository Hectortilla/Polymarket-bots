"""Bounded official-SDK search and exact lookup for market selectors."""

import asyncio
import logging
import re
from http import HTTPStatus
from dataclasses import replace

from polybot.polymarket.client_lifecycle import PublicClientLease
from polybot.polymarket.discovery_contracts import MarketSearchResults, MarketSuggestion
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.gamma import _GammaMarketSourceClient
from polybot.polymarket.normalization.discovery import normalize_suggestion

from polymarket import AsyncPublicClient, PolymarketError, RequestRejectedError

from polybot.polymarket.discovery_policy import DISCOVERY_TIMEOUT_SECONDS

ACTIVE_SEARCH_EVENTS = "active"
logger = logging.getLogger(__name__)


class MarketDiscovery:
    def __init__(self, client: AsyncPublicClient | None = None) -> None:
        self._lease = PublicClientLease.acquire(client)
        self._sources = _GammaMarketSourceClient(self._lease.client)

    async def search(self, query: str, limit: int) -> MarketSearchResults:
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
                if re.fullmatch(r"0x[a-fA-F0-9]{64}", query):
                    return await self._search_identifier(query, condition=True)
                if re.fullmatch(r"[0-9]+", query):
                    return await self._search_identifier(query, condition=False)
                page = await self._lease.client.search(
                    q=query,
                    events_status=ACTIVE_SEARCH_EVENTS,
                    search_profiles=False,
                    search_tags=False,
                    keep_closed_markets=0,
                    page_size=limit,
                ).first_page()
        except (PolymarketError, TimeoutError) as error:
            raise MarketDataTransportError("market search unavailable") from error

        suggestions: dict[str, MarketSuggestion] = {}
        for result in page.items:
            for event in result.events:
                for source in event.markets:
                    try:
                        suggestion = normalize_suggestion(
                            source, event_title=event.title
                        )
                    except MarketDataError as error:
                        # One unusable search hit must not hide other valid choices.
                        logger.warning(
                            "Skipping invalid market search result: %s", error
                        )
                        continue
                    previous = suggestions.get(suggestion.slug)
                    if previous is not None and replace(
                        previous, event_title=None
                    ) != replace(suggestion, event_title=None):
                        raise MarketDataError(
                            MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                            "search returned conflicting market identities",
                        )
                    suggestions[suggestion.slug] = suggestion
        available = tuple(
            choice for choice in suggestions.values() if choice.is_open_for_trading
        )
        return MarketSearchResults(
            markets=available[:limit],
            has_more=page.has_more or len(available) > limit,
        )

    async def resolve(self, slugs: tuple[str, ...]) -> tuple[MarketSuggestion, ...]:
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
                sources = await self._sources.find_many(slugs)
        except TimeoutError as error:
            raise MarketDataTransportError("market lookup unavailable") from error
        suggestions = []
        for source in sources:
            if source is not None:
                title = source.events[0].title if source.events else None
                suggestions.append(normalize_suggestion(source, event_title=title))
        return tuple(suggestions)

    async def close(self) -> None:
        await self._lease.close()

    async def _search_identifier(
        self, query: str, *, condition: bool
    ) -> MarketSearchResults:
        # Token IDs can exceed Gamma's integer range; query that index first.
        paginator = (
            self._lease.client.list_markets(condition_ids=(query,), page_size=2)
            if condition
            else self._lease.client.list_markets(clob_token_ids=(query,), page_size=2)
        )
        page = await paginator.first_page()
        if page.has_more or len(page.items) > 1:
            raise MarketDataError(
                MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                "market ID lookup is ambiguous",
            )
        sources = list(page.items)
        for source in sources:
            matches = (
                (source.condition_id or "").lower() == query.lower()
                if condition
                else any(
                    token.token_id == query
                    for token in (source.outcomes.yes, source.outcomes.no)
                )
            )
            if not matches:
                raise MarketDataError(
                    MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                    "market ID lookup returned another market",
                )
        if not sources and not condition:
            try:
                source = await self._lease.client.get_market(id=query)
            except RequestRejectedError as error:
                if error.status != HTTPStatus.NOT_FOUND:
                    raise
            else:
                if source.id != query:
                    raise MarketDataError(
                        MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                        "market ID lookup returned another market",
                    )
                sources.append(source)
        choices = tuple(
            normalize_suggestion(
                source, event_title=source.events[0].title if source.events else None
            )
            for source in sources
        )
        return MarketSearchResults(
            tuple(choice for choice in choices if choice.is_open_for_trading), False
        )
