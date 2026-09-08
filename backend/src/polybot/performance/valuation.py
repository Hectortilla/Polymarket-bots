"""Executable portfolio valuation shared by dashboards and result reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

from polybot.framework.events.books import BookSnapshot
from polybot.performance.contracts.valuation import (
    ZERO_MARKET_VALUE,
    PortfolioLike,
    PortfolioValuation,
    PortfolioValuationResult,
    PositionLike,
    PositionValuation,
)
from polybot.performance.contracts.valuation_status import (
    ValuationStatus,
    aggregate_valuation_status,
)


def value_portfolio(
    portfolio: PortfolioLike,
    books: Mapping[str, BookSnapshot],
    *,
    now_ms: int | None,
    max_book_age_ms: int | None,
    initial_cash_usdc: Decimal | None = None,
    last_executable_marks: Mapping[str, Decimal] | None = None,
    allow_stale_marks: bool = True,
) -> PortfolioValuationResult:
    """Mark open positions at the executable side of each current order book.

    Long positions are marked at the best bid and shorts at the best ask. A
    previously executable mark may be used only when ``allow_stale_marks`` is
    true, and the result is then explicitly classified as stale.
    """
    _validate_valuation_options(now_ms, max_book_age_ms)
    marks = dict(last_executable_marks or {})
    position_values = tuple(
        _value_position(
            position,
            books,
            now_ms=now_ms,
            max_book_age_ms=max_book_age_ms,
            last_executable_marks=marks,
            allow_stale_marks=allow_stale_marks,
        )
        for position in _portfolio_positions(portfolio)
    )
    status = _portfolio_status(position_values)
    if status is ValuationStatus.UNAVAILABLE:
        marked_value = None
        equity = None
        exposure = None
    else:
        market_values = tuple(
            _required_market_value(position) for position in position_values
        )
        marked_value = sum(market_values, ZERO_MARKET_VALUE)
        equity = portfolio.cash_usdc + marked_value
        exposure = sum((abs(value) for value in market_values), ZERO_MARKET_VALUE)
    pnl = (
        None
        if equity is None or initial_cash_usdc is None
        else equity - initial_cash_usdc
    )
    valuation = PortfolioValuation(
        cash_usdc=portfolio.cash_usdc,
        marked_position_value_usdc=marked_value,
        equity_usdc=equity,
        pnl_usdc=pnl,
        exposure_usdc=exposure,
        positions=position_values,
        status=status,
    )
    return PortfolioValuationResult(
        valuation=valuation,
        next_executable_marks=tuple(sorted(marks.items())),
    )


def _portfolio_positions(portfolio: PortfolioLike) -> tuple[PositionLike, ...]:
    raw_positions = portfolio.positions
    if isinstance(raw_positions, Mapping):
        values: Iterable[PositionLike] = raw_positions.values()
    else:
        values = raw_positions
    return tuple(sorted(values, key=lambda position: position.token_id))


def _value_position(
    position: PositionLike,
    books: Mapping[str, BookSnapshot],
    *,
    now_ms: int | None,
    max_book_age_ms: int | None,
    last_executable_marks: dict[str, Decimal],
    allow_stale_marks: bool,
) -> PositionValuation:
    book = _current_book(
        books.get(position.token_id),
        now_ms=now_ms,
        max_book_age_ms=max_book_age_ms,
    )
    executable_mark = None if book is None else book.executable_mark(position.size)
    if executable_mark is not None:
        last_executable_marks[position.token_id] = executable_mark
        return PositionValuation(
            token_id=position.token_id,
            size=position.size,
            average_entry_price=position.average_entry_price,
            executable_mark=executable_mark,
            last_executable_mark=None,
            market_value_usdc=position.size * executable_mark,
            status=ValuationStatus.FRESH,
        )
    stale_mark = (
        last_executable_marks.get(position.token_id) if allow_stale_marks else None
    )
    if stale_mark is not None:
        return PositionValuation(
            token_id=position.token_id,
            size=position.size,
            average_entry_price=position.average_entry_price,
            executable_mark=None,
            last_executable_mark=stale_mark,
            market_value_usdc=position.size * stale_mark,
            status=ValuationStatus.STALE,
        )
    return PositionValuation(
        token_id=position.token_id,
        size=position.size,
        average_entry_price=position.average_entry_price,
        executable_mark=None,
        last_executable_mark=None,
        market_value_usdc=None,
        status=ValuationStatus.UNAVAILABLE,
    )


def _current_book(
    book: BookSnapshot | None,
    *,
    now_ms: int | None,
    max_book_age_ms: int | None,
) -> BookSnapshot | None:
    if book is None or max_book_age_ms is None:
        return book
    assert now_ms is not None  # Validated by value_portfolio at the public boundary.
    return book if book.is_fresh(now_ms, max_book_age_ms) else None


def _portfolio_status(
    positions: tuple[PositionValuation, ...],
) -> ValuationStatus:
    return aggregate_valuation_status(position.status for position in positions)


def _validate_valuation_options(
    now_ms: int | None,
    max_book_age_ms: int | None,
) -> None:
    if max_book_age_ms is not None and (
        isinstance(max_book_age_ms, bool)
        or not isinstance(max_book_age_ms, int)
        or max_book_age_ms < 0
    ):
        raise ValueError("maximum book age must be a nonnegative integer")
    if max_book_age_ms is not None and (
        isinstance(now_ms, bool)
        or not isinstance(now_ms, int)
        or now_ms < 0
    ):
        raise ValueError("now_ms is required and must be nonnegative")


def _required_market_value(position: PositionValuation) -> Decimal:
    if position.market_value_usdc is None:
        raise AssertionError("available portfolio valuation requires position values")
    return position.market_value_usdc
