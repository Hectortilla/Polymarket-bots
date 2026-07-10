from __future__ import annotations

from decimal import Decimal

from bots.framework.context import BookClient, MarketClient
from bots.framework.events import FillRejectReason, OrderRequest
from bots.framework.events.books import BookSnapshot
from bots.execution.paper.validation import valid_fee_rate

MARKET_UNAVAILABLE_MESSAGE = "fill-time market metadata was unavailable"
MARKET_FEE_INVALID_MESSAGE = "fill-time market fee rate was invalid"


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
) -> tuple[Decimal | None, tuple[FillRejectReason, str] | None]:
    market_slug = order.market_slug or book.market_slug
    if market_slug is None or markets is None:
        return None, (FillRejectReason.MARKET_UNAVAILABLE, MARKET_UNAVAILABLE_MESSAGE)
    try:
        market = await markets.find_by_slug(market_slug)
    except Exception:
        market = None
    if market is None:
        return None, (FillRejectReason.MARKET_UNAVAILABLE, MARKET_UNAVAILABLE_MESSAGE)
    try:
        fee_rate = valid_fee_rate(market.fee_rate)
    except Exception:
        fee_rate = None
    if fee_rate is None:
        return None, (FillRejectReason.MARKET_FEE_INVALID, MARKET_FEE_INVALID_MESSAGE)
    return fee_rate, None
