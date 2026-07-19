"""Validation shared by market-discovery and resolution boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.markets import Market
from polybot.polymarket.positions import Position


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    condition_id: str | None
    token_ids: tuple[str, ...]
    market_slug: str | None

    @classmethod
    def from_position(cls, position: Position) -> MarketIdentity:
        return cls(position.condition_id, (position.token_id,), position.market_slug)

    def matches(self, market: Market) -> bool:
        return (
            self.condition_id == market.condition_id
            and bool(self.token_ids)
            and set(self.token_ids).issubset(market.token_ids)
            and (self.market_slug is None or self.market_slug == market.slug)
        )


def validate_position_market_identity(
    position: Position,
    market: Market | None,
    error_message: str,
) -> None:
    if market is None or not MarketIdentity.from_position(position).matches(market):
        raise RuntimeError(error_message)


def validate_market_reference(
    market: Market | None,
    *,
    token_id: str,
    condition_id: str,
    market_slug: str,
    error_message: str,
) -> None:
    identity = MarketIdentity(condition_id, (token_id,), market_slug)
    if market is None or not identity.matches(market):
        raise RuntimeError(error_message)


def validate_resolution_market_identity(
    event: MarketResolutionEvent,
    market: Market,
    error_message: str,
) -> None:
    if (
        not _matches_market(
            market,
            condition_id=event.condition_id,
            token_ids=event.token_ids,
            market_slug=event.market_slug,
        )
        or event.winning_token_id not in event.token_ids
    ):
        raise ValueError(error_message)


def validate_wallet_trade_market_identity(
    trade: WalletTradeEvent,
    market: Market | None,
    error_message: str,
) -> None:
    if market is None or not _matches_market(
        market,
        condition_id=trade.condition_id,
        token_id=trade.token_id,
        market_slug=trade.market_slug,
    ):
        raise RuntimeError(error_message)


def _matches_market(
    market: Market,
    *,
    condition_id: str | None,
    token_ids: tuple[str, ...] = (),
    token_id: str | None = None,
    market_slug: str | None,
) -> bool:
    return (
        condition_id == market.condition_id
        and (
            (
                token_id is not None
                and token_id in set(market.token_ids)
            )
            or (
                token_id is None
                and len(token_ids) == 2
                and set(token_ids) == set(market.token_ids)
            )
        )
        and (market_slug is None or market_slug == market.slug)
    )
