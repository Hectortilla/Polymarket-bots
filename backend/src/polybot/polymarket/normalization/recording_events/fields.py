"""Shared vendor field normalization for recorded market events."""

from polybot.framework.events import Side
from polybot.polymarket.errors import MarketDataError, MarketDataIssue


def normalize_side(value: object) -> Side:
    try:
        return Side(value)
    except (TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_SIDE,
            "market-channel side is invalid",
        ) from error
