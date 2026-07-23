"""Validation shared by market-discovery and resolution boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.markets import Market
from polybot.polymarket.positions.contracts import Position


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    condition_id: str | None
    token_ids: tuple[str, ...]
    market_slug: str | None

    @classmethod
    def from_position(cls, position: Position) -> MarketIdentity:
        return cls(position.condition_id, (position.token_id,), position.market_slug)

    @classmethod
    def from_market_reference(
        cls,
        *,
        token_id: str,
        condition_id: str,
        market_slug: str,
    ) -> MarketIdentity:
        return cls(condition_id, (token_id,), market_slug)

    @classmethod
    def from_resolution(cls, event: MarketResolutionEvent) -> MarketIdentity:
        return cls(event.condition_id, event.token_ids, event.market_slug)

    @classmethod
    def from_wallet_trade(cls, trade: WalletTradeEvent) -> MarketIdentity:
        return cls(trade.condition_id, (trade.token_id,), trade.market_slug)

    def matches(self, market: Market) -> bool:
        return (
            self.condition_id == market.condition_id
            and bool(self.token_ids)
            and set(self.token_ids).issubset(market.token_ids)
            and (self.market_slug is None or self.market_slug == market.slug)
        )

    def matches_complete_token_pair(self, market: Market) -> bool:
        return (
            self.condition_id == market.condition_id
            and len(self.token_ids) == 2
            and set(self.token_ids) == set(market.token_ids)
            and (self.market_slug is None or self.market_slug == market.slug)
        )

    def contains_token(self, token_id: str) -> bool:
        return token_id in self.token_ids
