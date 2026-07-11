from __future__ import annotations

from collections.abc import Iterable

from polymarket.models.clob.order_book import OrderBookLevel

from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.polymarket.errors import MarketDataError, MarketDataIssue

from .values import _required_text


def normalize_book(
    *,
    token_id: object,
    bids: Iterable[OrderBookLevel],
    asks: Iterable[OrderBookLevel],
    received_at_ms: int,
    condition_id: object = None,
    market_slug: str | None = None,
    outcome: str | None = None,
    expected_token_id: str | None = None,
    expected_condition_id: str | None = None,
) -> BookSnapshot:
    normalized_token_id = _required_text(
        token_id,
        MarketDataIssue.MISSING_TOKEN_ID,
        "book token ID",
    )
    normalized_condition_id = _required_text(
        condition_id,
        MarketDataIssue.MISSING_CONDITION_ID,
        "book condition ID",
    )
    if expected_token_id is not None and normalized_token_id != expected_token_id:
        raise MarketDataError(
            MarketDataIssue.BOOK_IDENTITY_MISMATCH,
            "book token ID does not match the requested token",
        )
    if (
        expected_condition_id is not None
        and normalized_condition_id != expected_condition_id
    ):
        raise MarketDataError(
            MarketDataIssue.BOOK_IDENTITY_MISMATCH,
            "book condition ID does not match the resolved market",
        )

    normalized_bids = _levels(bids, reverse=True)
    normalized_asks = _levels(asks, reverse=False)
    snapshot = BookSnapshot(
        token_id=normalized_token_id,
        bids=normalized_bids,
        asks=normalized_asks,
        received_at_ms=received_at_ms,
        market_slug=market_slug,
        condition_id=normalized_condition_id,
        outcome=outcome,
    )
    if snapshot.is_crossed():
        raise MarketDataError(
            MarketDataIssue.CROSSED_BOOK,
            f"book for token {normalized_token_id} is crossed",
        )
    return snapshot


def normalize_price_change_level(
    *,
    price: object,
    size: object,
) -> BookLevel:
    try:
        level = BookLevel(price=price, size=size)  # type: ignore[arg-type]
    except (AttributeError, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "price change level is malformed",
        ) from error
    if not level.is_valid_price() or not level.is_valid_size(allow_zero=True):
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "price change level has an invalid price or size",
        )
    return level


def _levels(
    source: Iterable[OrderBookLevel],
    *,
    reverse: bool,
) -> tuple[BookLevel, ...]:
    try:
        levels = tuple(_normalize_level(level) for level in source)
    except MarketDataError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "order book depth is malformed",
        ) from error
    return tuple(sorted(levels, key=lambda level: level.price, reverse=reverse))


def _normalize_level(level: OrderBookLevel) -> BookLevel:
    try:
        normalized = BookLevel(price=level.price, size=level.size)
    except (AttributeError, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "order book depth is malformed",
        ) from error
    if not normalized.is_valid():
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "order book contains an invalid price or size",
        )
    return normalized
