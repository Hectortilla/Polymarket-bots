from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import Market

MARKET_ADDITION_BATCH_SECONDS = 0.1


class TrackedMarketLimitExceeded(RuntimeError):
    """Adding an unresolved condition would exceed the caller's runtime cap."""


class MarketInterest(StrEnum):
    CONFIGURED = "configured"
    FOLLOWED_WALLET = "followed_wallet"
    BROKER_POSITION = "broker_position"


@dataclass(slots=True)
class TrackedMarket:
    market: Market
    interests: set[MarketInterest] = field(default_factory=set)
    owners: set[str] = field(default_factory=set)


class TrackedMarketRegistry:
    """Runtime-owned, condition-keyed union of every unresolved market interest."""

    def __init__(
        self,
        *,
        terminal_condition_ids: Iterable[str] = (),
        max_tracked_markets: int | None = None,
    ) -> None:
        if max_tracked_markets is not None and (
            isinstance(max_tracked_markets, bool)
            or not isinstance(max_tracked_markets, int)
            or max_tracked_markets < 1
        ):
            raise ValueError("max_tracked_markets must be a positive integer")
        self._max_tracked_markets = max_tracked_markets
        self._entries: dict[str, TrackedMarket] = {}
        self._terminal_condition_ids = frozenset(
            condition_id for condition_id in terminal_condition_ids if condition_id
        )
        self._revision = 0
        self._changed = asyncio.Event()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def entries(self) -> tuple[TrackedMarket, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))

    @property
    def markets(self) -> tuple[Market, ...]:
        return tuple(entry.market for entry in self.entries)

    @property
    def token_ids(self) -> frozenset[str]:
        return frozenset(
            token_id
            for entry in self._entries.values()
            for token_id in entry.market.token_ids
        )

    @property
    def terminal_condition_ids(self) -> frozenset[str]:
        return self._terminal_condition_ids

    def is_terminal(self, condition_id: str) -> bool:
        return condition_id in self._terminal_condition_ids

    def get(self, condition_id: str) -> TrackedMarket | None:
        return self._entries.get(condition_id)

    def ensure_compatible(self, market: Market) -> None:
        """Reject a different token pair for an already tracked condition."""

        entry = self._entries.get(market.condition_id)
        if entry is not None and set(entry.market.token_ids) != set(market.token_ids):
            raise MarketDataError(
                MarketDataIssue.AMBIGUOUS_MARKET_METADATA,
                f"condition ID maps to conflicting token pairs: {market.condition_id}",
            )

    def require_capacity(self, market: Market) -> None:
        if (
            market.condition_id not in self._entries
            and not self.is_terminal(market.condition_id)
            and self._max_tracked_markets is not None
            and len(self._entries) >= self._max_tracked_markets
        ):
            raise TrackedMarketLimitExceeded("tracked-market allowance reached")

    def add(
        self,
        market: Market,
        interest: MarketInterest,
        *,
        owner: str | None = None,
    ) -> bool:
        if self.is_terminal(market.condition_id):
            return False
        entry = self._entries.get(market.condition_id)
        subscription_changed = False
        if entry is None:
            self.require_capacity(market)
            entry = TrackedMarket(market)
            self._entries[market.condition_id] = entry
            changed = True
            subscription_changed = True
        else:
            self.ensure_compatible(market)
            changed = entry.market != market
            entry.market = market
        if interest not in entry.interests:
            entry.interests.add(interest)
            changed = True
        if owner is not None and owner not in entry.owners:
            entry.owners.add(owner)
            changed = True
        if subscription_changed:
            self._notify_change()
        return changed

    def resolve(self, condition_id: str) -> bool:
        self._terminal_condition_ids = self._terminal_condition_ids | {condition_id}
        if self._entries.pop(condition_id, None) is None:
            return False
        self._notify_change()
        return True

    async def wait_for_change(
        self,
        revision: int,
        *,
        batch_seconds: float = MARKET_ADDITION_BATCH_SECONDS,
    ) -> int:
        while self._revision == revision:
            self._changed.clear()
            if self._revision != revision:
                break
            await self._changed.wait()
        if batch_seconds > 0:
            await asyncio.sleep(batch_seconds)
        return self._revision

    def _notify_change(self) -> None:
        self._revision += 1
        self._changed.set()
