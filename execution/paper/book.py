from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from bots.framework.book_validation import BOOK_PRICE_CEILING, ZERO_DECIMAL
from bots.framework.events import BookLevel, BookSnapshot, Side


@dataclass(frozen=True, slots=True)
class ConsumedLevel:
    price: Decimal
    size: Decimal
    notional_usdc: Decimal


def ordered_levels(side: Side, book: BookSnapshot) -> tuple[BookLevel, ...]:
    if side is Side.BUY:
        return tuple(sorted(book.asks, key=lambda level: level.price))
    return tuple(sorted(book.bids, key=lambda level: level.price, reverse=True))


def slippage_limit_price(
    *,
    side: Side,
    reference_price: Decimal,
    max_slippage_pct: Decimal,
) -> Decimal:
    if side is Side.BUY:
        return reference_price * (BOOK_PRICE_CEILING + max_slippage_pct)
    return reference_price * (BOOK_PRICE_CEILING - max_slippage_pct)


def consume_levels(
    side: Side,
    levels: tuple[BookLevel, ...],
    *,
    requested_size: Decimal,
    slippage_limit_price: Decimal,
) -> tuple[ConsumedLevel, ...]:
    remaining = requested_size
    consumed: list[ConsumedLevel] = []

    for level in levels:
        if remaining <= ZERO_DECIMAL:
            break
        if not _within_slippage(side, level.price, slippage_limit_price):
            break

        fill_size = min(level.size, remaining)

        consumed.append(
            ConsumedLevel(
                price=level.price,
                size=fill_size,
                notional_usdc=fill_size * level.price,
            )
        )
        remaining -= fill_size

    return tuple(consumed)


def _within_slippage(
    side: Side,
    price: Decimal,
    slippage_limit_price: Decimal,
) -> bool:
    if side is Side.BUY:
        return price <= slippage_limit_price
    return price >= slippage_limit_price
