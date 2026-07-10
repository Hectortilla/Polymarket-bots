from decimal import Decimal

import pytest

from bots.execution.paper.book import consume_levels, slippage_limit_price
from bots.framework.events import BookLevel, BookSnapshot, Side


@pytest.mark.parametrize(
    ("price", "size"),
    (
        (Decimal("0"), Decimal("1")),
        (Decimal("1.01"), Decimal("1")),
        (Decimal("0.50"), Decimal("0")),
        (Decimal("0.50"), Decimal("-1")),
        (Decimal("Infinity"), Decimal("1")),
        (Decimal("0.50"), Decimal("Infinity")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("0.50"), Decimal("NaN")),
    ),
)
def test_book_level_rejects_invalid_values(price: Decimal, size: Decimal) -> None:
    assert BookLevel(price=price, size=size).is_valid() is False


def test_book_snapshot_validates_all_levels() -> None:
    valid = BookLevel(price=Decimal("0.50"), size=Decimal("2"))
    invalid = BookLevel(price=Decimal("0.60"), size=Decimal("Infinity"))

    assert _book(bids=(valid,), asks=(valid,)).has_valid_levels() is True
    assert _book(bids=(valid,), asks=(invalid,)).has_valid_levels() is False


@pytest.mark.parametrize(
    ("bids", "asks"),
    (
        ((object(),), ()),
        ((), (object(),)),
        (None, ()),
        ((), None),
    ),
)
def test_book_snapshot_rejects_malformed_depth(
    bids: object,
    asks: object,
) -> None:
    book = BookSnapshot(
        token_id="token",
        bids=bids,  # type: ignore[arg-type]
        asks=asks,  # type: ignore[arg-type]
        received_at_ms=1_000,
    )

    assert book.has_valid_levels() is False


def test_book_snapshot_orders_executable_levels_for_each_side() -> None:
    low = BookLevel(price=Decimal("0.40"), size=Decimal("1"))
    high = BookLevel(price=Decimal("0.70"), size=Decimal("1"))
    book = _book(bids=(low, high), asks=(high, low))

    assert book.executable_levels(Side.BUY) == (low, high)
    assert book.executable_levels(Side.SELL) == (high, low)


def test_sell_slippage_limit_is_inclusive_and_stops_at_worse_price() -> None:
    limit = slippage_limit_price(
        side=Side.SELL,
        reference_price=Decimal("0.50"),
        max_slippage_pct=Decimal("0.02"),
    )
    at_limit = BookLevel(price=limit, size=Decimal("1"))
    below_limit = BookLevel(price=limit - Decimal("0.01"), size=Decimal("1"))

    consumed = consume_levels(
        Side.SELL,
        (at_limit, below_limit),
        requested_size=Decimal("2"),
        slippage_limit_price=limit,
    )

    assert tuple(level.price for level in consumed) == (limit,)


def _book(
    *,
    bids: tuple[BookLevel, ...],
    asks: tuple[BookLevel, ...],
) -> BookSnapshot:
    return BookSnapshot(
        token_id="token",
        bids=bids,
        asks=asks,
        received_at_ms=1_000,
    )
