from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from polymarket.models.clob.order_book import OrderBookLevel
from polymarket.models.gamma.market import Market as SdkMarket

from bots.framework.events.books import BookLevel, BookSnapshot
from bots.polymarket.errors import MarketDataError, MarketDataIssue
from bots.polymarket.types import Market


def normalize_market(source: SdkMarket) -> Market:
    condition_id = _required_text(
        source.condition_id,
        MarketDataIssue.MISSING_CONDITION_ID,
        "market condition ID",
    )
    slug = _required_text(
        source.slug,
        MarketDataIssue.MISSING_MARKET_SLUG,
        "market slug",
    )
    question = _required_text(
        source.question,
        MarketDataIssue.MISSING_QUESTION,
        "market question",
    )
    yes_token_id = _required_text(
        source.outcomes.yes.token_id,
        MarketDataIssue.MISSING_TOKEN_ID,
        "YES token ID",
    )
    no_token_id = _required_text(
        source.outcomes.no.token_id,
        MarketDataIssue.MISSING_TOKEN_ID,
        "NO token ID",
    )
    minimum_tick_size = _positive_decimal(
        source.trading.minimum_tick_size,
        "minimum tick size",
    )
    minimum_order_size = _positive_decimal(
        source.trading.minimum_order_size,
        "minimum order size",
    )
    if not isinstance(source.state.neg_risk, bool):
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            "market negative-risk flag is missing",
        )

    fee_rate = Decimal("0")
    if source.trading.fees_enabled:
        fee_schedule = source.trading.fee_schedule
        if fee_schedule is None:
            raise MarketDataError(
                MarketDataIssue.INVALID_MARKET_PARAMETERS,
                "fee-enabled market has no fee schedule",
            )
        fee_rate = _non_negative_decimal(fee_schedule.rate, "fee rate")

    return Market(
        condition_id=condition_id,
        slug=slug,
        question=question,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        minimum_tick_size=minimum_tick_size,
        minimum_order_size=minimum_order_size,
        neg_risk=source.state.neg_risk,
        fee_rate=fee_rate,
    )


def normalize_book(
    *,
    token_id: object,
    bids: Iterable[OrderBookLevel],
    asks: Iterable[OrderBookLevel],
    received_at_ms: int,
    condition_id: object = None,
    market_slug: str | None = None,
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
    normalized_bids = _levels(bids, reverse=True)
    normalized_asks = _levels(asks, reverse=False)
    snapshot = BookSnapshot(
        token_id=normalized_token_id,
        bids=normalized_bids,
        asks=normalized_asks,
        received_at_ms=received_at_ms,
        market_slug=market_slug,
        condition_id=normalized_condition_id,
    )
    if snapshot.is_crossed():
        raise MarketDataError(
            MarketDataIssue.CROSSED_BOOK,
            f"book for token {normalized_token_id} is crossed",
        )
    return snapshot


def _levels(
    source: Iterable[OrderBookLevel],
    *,
    reverse: bool,
) -> tuple[BookLevel, ...]:
    try:
        levels = tuple(
            BookLevel(price=level.price, size=level.size)
            for level in source
        )
    except (AttributeError, TypeError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "order book depth is malformed",
        ) from error
    if not all(level.is_valid() for level in levels):
        raise MarketDataError(
            MarketDataIssue.INVALID_BOOK_LEVEL,
            "order book contains an invalid price or size",
        )
    return tuple(sorted(levels, key=lambda level: level.price, reverse=reverse))


def _required_text(value: object, issue: MarketDataIssue, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise MarketDataError(issue, f"{field} is missing")
    return normalized


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _positive_decimal(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if normalized <= 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must be positive",
        )
    return normalized


def _non_negative_decimal(value: object, field: str) -> Decimal:
    normalized = _decimal(value, field)
    if normalized < 0:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} must not be negative",
        )
    return normalized


def _decimal(value: object, field: str) -> Decimal:
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
        if not normalized.is_finite():
            raise InvalidOperation
        return normalized
    except (InvalidOperation, TypeError, ValueError) as error:
        raise MarketDataError(
            MarketDataIssue.INVALID_MARKET_PARAMETERS,
            f"{field} is invalid",
        ) from error
