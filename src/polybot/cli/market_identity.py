"""Validation shared by market-discovery and resolution boundaries."""

from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.types import Market, Position, market_token_ids


def validate_position_market_identity(
    position: Position,
    market: Market | None,
    error_message: str,
) -> None:
    if market is None or not _matches_market(
        market,
        condition_id=position.condition_id,
        token_id=position.token_id,
        market_slug=position.market_slug,
    ):
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
                and token_id in set(market_token_ids(market))
            )
            or (
                token_id is None
                and len(token_ids) == 2
                and set(token_ids) == set(market_token_ids(market))
            )
        )
        and (market_slug is None or market_slug == market.slug)
    )
