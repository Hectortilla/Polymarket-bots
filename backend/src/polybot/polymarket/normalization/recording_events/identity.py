from __future__ import annotations

from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.markets import Market
from polybot.polymarket.normalization.values import require_text
from polybot.recording.contracts.market import MarketIdentity


def _condition_id(value: object, market: Market) -> str:
    condition_id = require_text(value, "condition ID")
    if condition_id != market.condition_id:
        raise MarketDataError(
            MarketDataIssue.BOOK_IDENTITY_MISMATCH,
            "market-channel condition ID does not match resolved metadata",
        )
    return condition_id


def _token_id(value: object, market: Market) -> str:
    token_id = require_text(value, "token ID")
    if token_id not in market.token_ids:
        raise MarketDataError(
            MarketDataIssue.BOOK_IDENTITY_MISMATCH,
            "market-channel token ID does not match resolved metadata",
        )
    return token_id


def _token_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise MarketDataError(
            MarketDataIssue.INVALID_RESOLUTION,
            "resolved token IDs are missing",
        )
    return tuple(require_text(token_id, "resolved token ID") for token_id in value)


def _identity(market: Market, token_id: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        condition_id=market.condition_id,
        market_slug=market.slug,
        token_id=token_id,
    )
