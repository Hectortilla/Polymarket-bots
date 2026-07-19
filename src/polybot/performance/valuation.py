"""Executable portfolio valuation shared by dashboards and result reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, cast

from polybot.framework.events.books import BookSnapshot


ZERO_MARKET_VALUE = Decimal("0")


class ValuationStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class PositionLike(Protocol):
    token_id: str
    size: Decimal
    average_entry_price: Decimal | None


class PortfolioLike(Protocol):
    cash_usdc: Decimal
    cumulative_fees_usdc: Decimal


@dataclass(frozen=True, slots=True)
class PositionValuation:
    token_id: str
    size: Decimal
    average_entry_price: Decimal | None
    executable_mark: Decimal | None
    last_executable_mark: Decimal | None
    market_value_usdc: Decimal | None
    status: ValuationStatus

    @property
    def effective_mark(self) -> Decimal | None:
        if self.executable_mark is not None:
            return self.executable_mark
        return self.last_executable_mark


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    cash_usdc: Decimal
    marked_position_value_usdc: Decimal | None
    equity_usdc: Decimal | None
    pnl_usdc: Decimal | None
    exposure_usdc: Decimal | None
    positions: tuple[PositionValuation, ...]
    status: ValuationStatus

    @property
    def equity(self) -> Decimal | None:
        """Compatibility alias used by the terminal dashboard."""
        return self.equity_usdc

    @property
    def pnl(self) -> Decimal | None:
        """Compatibility alias used by the terminal dashboard."""
        return self.pnl_usdc

    @property
    def is_stale(self) -> bool:
        return self.status is ValuationStatus.STALE

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @classmethod
    def unavailable(
        cls, cash_usdc: Decimal = ZERO_MARKET_VALUE
    ) -> PortfolioValuation:
        return cls(
            cash_usdc=cash_usdc,
            marked_position_value_usdc=None,
            equity_usdc=None,
            pnl_usdc=None,
            exposure_usdc=None,
            positions=(),
            status=ValuationStatus.UNAVAILABLE,
        )


@dataclass(frozen=True, slots=True)
class PortfolioValuationResult:
    valuation: PortfolioValuation
    next_executable_marks: tuple[tuple[str, Decimal], ...]

    def marks(self) -> dict[str, Decimal]:
        return dict(self.next_executable_marks)


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
    raw_positions = getattr(portfolio, "positions", ())
    if isinstance(raw_positions, Mapping):
        values: Iterable[object] = raw_positions.values()
    else:
        values = cast(Iterable[object], raw_positions)
    return tuple(
        sorted(
            cast(Iterable[PositionLike], values),
            key=lambda position: position.token_id,
        )
    )


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
    if now_ms is None:
        raise ValueError("now_ms is required when book freshness is enforced")
    return book if book.is_fresh(now_ms, max_book_age_ms) else None


def _portfolio_status(
    positions: tuple[PositionValuation, ...],
) -> ValuationStatus:
    return aggregate_valuation_status(position.status for position in positions)


def aggregate_valuation_status(
    statuses: Iterable[ValuationStatus],
) -> ValuationStatus:
    observed = set(statuses)
    if ValuationStatus.UNAVAILABLE in observed:
        return ValuationStatus.UNAVAILABLE
    if ValuationStatus.STALE in observed:
        return ValuationStatus.STALE
    return ValuationStatus.FRESH


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
