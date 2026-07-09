from __future__ import annotations

from decimal import Decimal, InvalidOperation

from bots.framework.events import BookSnapshot

ZERO_DECIMAL = Decimal("0")
BOOK_PRICE_CEILING = Decimal("1")


def is_valid_book_level(level: object) -> bool:
    try:
        price = getattr(level, "price")
        size = getattr(level, "size")
        return ZERO_DECIMAL < price <= BOOK_PRICE_CEILING and size > ZERO_DECIMAL
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return False


def book_levels_are_valid(book: BookSnapshot) -> bool:
    return all(is_valid_book_level(level) for level in (*book.bids, *book.asks))
