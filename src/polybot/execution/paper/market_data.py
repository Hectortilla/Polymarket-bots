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


async def resolve_fee_rate(
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
    if not market_matches_order_and_book(market, order, book):
        return None, (
            FillRejectReason.MARKET_METADATA_MISMATCH,
            MARKET_METADATA_MISMATCH_MESSAGE,
        )
    return FillMarketData(market=market, fee_rate=fee_rate), None


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
