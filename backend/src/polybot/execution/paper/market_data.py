from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.context import BookClient, MarketClient
from polybot.framework.events import FillRejectReason, OrderRequest
from polybot.framework.events.books import BookSnapshot
from polybot.execution.paper.validation import valid_fee_rate
from polybot.polymarket.markets import Market

MARKET_UNAVAILABLE_MESSAGE = "fill-time market metadata was unavailable"
MARKET_FEE_INVALID_MESSAGE = "fill-time market fee rate was invalid"
MARKET_METADATA_MISMATCH_MESSAGE = "fill-time market metadata did not match the order"
MARKET_RESOLVED_MESSAGE = "market is already resolved or settled"
MARKET_NOT_TRADABLE_MESSAGE = "fill-time market was not open for trading"
MARKET_CONSTRAINTS_UNAVAILABLE_MESSAGE = (
    "fill-time market trading limits were unavailable"
)
MARKET_TICK_SIZE_MESSAGE = "order price does not conform to the market tick size"
MARKET_MINIMUM_ORDER_SIZE_MESSAGE = "order size is below the market minimum"


@dataclass(frozen=True, slots=True)
class FillMarketData:
    market: Market
    fee_rate: Decimal


async def latest_book(
    books: BookClient,
    token_id: str,
) -> BookSnapshot | None:
    try:
        return await books.latest(token_id)
    except Exception:
        return None


async def resolve_fill_market_data(
    markets: MarketClient | None,
    order: OrderRequest,
    book: BookSnapshot,
) -> tuple[FillMarketData | None, tuple[FillRejectReason, str] | None]:
    market_slug = order.market_slug or book.market_slug
    if market_slug is None or markets is None:
        return None, (FillRejectReason.MARKET_UNAVAILABLE, MARKET_UNAVAILABLE_MESSAGE)
    try:
        market = await markets.find_by_slug(market_slug)
    except Exception:
        market = None
    if market is None:
        return None, (FillRejectReason.MARKET_UNAVAILABLE, MARKET_UNAVAILABLE_MESSAGE)
    if getattr(market, "resolved", False) is True:
        return None, (FillRejectReason.MARKET_RESOLVED, MARKET_RESOLVED_MESSAGE)
    try:
        fee_rate = valid_fee_rate(market.fee_rate)
    except Exception:
        fee_rate = None
    if fee_rate is None:
        return None, (FillRejectReason.MARKET_FEE_INVALID, MARKET_FEE_INVALID_MESSAGE)
    if not getattr(market, "is_open_for_trading", False):
        return None, (FillRejectReason.MARKET_UNAVAILABLE, MARKET_NOT_TRADABLE_MESSAGE)
    market_data = FillMarketData(market=market, fee_rate=fee_rate)
    validation_reject = validate_fill_market_data(market_data, order, book)
    if validation_reject is not None:
        return None, validation_reject
    return market_data, None


def validate_fill_market_data(
    market_data: FillMarketData,
    order: OrderRequest,
    book: BookSnapshot,
) -> tuple[FillRejectReason, str] | None:
    """Validate already-fetched market data against one fill-time book snapshot."""
    market = market_data.market
    if not market_matches_order_and_book(market, order, book):
        return (
            FillRejectReason.MARKET_METADATA_MISMATCH,
            MARKET_METADATA_MISMATCH_MESSAGE,
        )
    constraint_reject = _validate_order_constraints(order, market)
    if constraint_reject is not None:
        return constraint_reject
    return None


def market_matches_order_and_book(
    market: Market, order: OrderRequest, book: BookSnapshot
) -> bool:
    market_slug = getattr(market, "slug", None)
    condition_id = getattr(market, "condition_id", None)
    if not all(
        isinstance(value, str) and value for value in (market_slug, condition_id)
    ):
        return False
    if book.market_slug != market_slug or book.condition_id != condition_id:
        return False
    token_ids = getattr(market, "token_ids", ())
    if not isinstance(token_ids, tuple) or not all(
        isinstance(token_id, str) and token_id for token_id in token_ids
    ):
        return False
    if book.token_id not in token_ids:
        return False
    if order.market_slug is not None and order.market_slug != market_slug:
        return False
    if order.condition_id is not None and order.condition_id != condition_id:
        return False
    return order.token_id in token_ids


def _validate_order_constraints(
    order: OrderRequest,
    market: Market,
) -> tuple[FillRejectReason, str] | None:
    tick_size = _positive_decimal_or_none(market.minimum_tick_size)
    minimum_order_size = _positive_decimal_or_none(market.minimum_order_size)
    if tick_size is None or minimum_order_size is None:
        return (
            FillRejectReason.MARKET_UNAVAILABLE,
            MARKET_CONSTRAINTS_UNAVAILABLE_MESSAGE,
        )
    if order.size < minimum_order_size:
        return FillRejectReason.BAD_SIZE, MARKET_MINIMUM_ORDER_SIZE_MESSAGE
    if not _is_tick_aligned(order.price, tick_size):
        return FillRejectReason.BAD_PRICE, MARKET_TICK_SIZE_MESSAGE
    return None


def _positive_decimal_or_none(value: object) -> Decimal | None:
    if not isinstance(value, Decimal):
        return None
    try:
        return value if value.is_finite() and value > 0 else None
    except Exception:
        return None


def _is_tick_aligned(price: Decimal, tick_size: Decimal) -> bool:
    try:
        ticks = price / tick_size
        return ticks == ticks.to_integral_value()
    except Exception:
        return False
