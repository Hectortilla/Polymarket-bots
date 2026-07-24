"""Portfolio valuation sampling for streamed performance artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.events.books import BookSnapshot
from polybot.performance.contracts.files import EquityField
from polybot.performance.contracts.run import SampleReason
from polybot.performance.contracts.valuation import (
    PortfolioLike,
    PortfolioValuation,
)
from polybot.performance.metrics import EquityCurveMetrics
from polybot.performance.valuation import value_portfolio

from .serialization import decimal_text, optional_decimal_text


@dataclass(frozen=True, slots=True)
class PortfolioSample:
    """One valuation and its already-normalized CSV row."""

    valuation: PortfolioValuation
    row: dict[str, object]


class PerformanceValuationSampler:
    """Own current books, reusable executable marks, and equity-curve state."""

    def __init__(
        self,
        *,
        initial_cash_usdc: Decimal,
        max_book_age_ms: int | None,
    ) -> None:
        self._initial_cash_usdc = initial_cash_usdc
        self._max_book_age_ms = max_book_age_ms
        self._books: dict[str, BookSnapshot] = {}
        self._last_executable_marks: dict[str, Decimal] = {}
        self._curve = EquityCurveMetrics()

    @property
    def books(self) -> Mapping[str, BookSnapshot]:
        return self._books

    @property
    def last_executable_marks(self) -> Mapping[str, Decimal]:
        return self._last_executable_marks

    @property
    def curve(self) -> EquityCurveMetrics:
        return self._curve

    def record_book(self, book: BookSnapshot) -> None:
        self._books[book.token_id] = book

    def remove_books(self, token_ids: tuple[str, ...]) -> None:
        for token_id in token_ids:
            self._books.pop(token_id, None)
            self._last_executable_marks.pop(token_id, None)

    def sample(
        self,
        timestamp_ms: int,
        reason: SampleReason,
        portfolio: PortfolioLike,
    ) -> PortfolioSample:
        valuation_result = value_portfolio(
            portfolio,
            self._books,
            now_ms=timestamp_ms,
            max_book_age_ms=self._max_book_age_ms,
            initial_cash_usdc=self._initial_cash_usdc,
            last_executable_marks=self._last_executable_marks,
            allow_stale_marks=True,
        )
        valuation = valuation_result.valuation
        self._last_executable_marks = valuation_result.marks()
        self._curve = self._curve.after_sample(timestamp_ms, valuation)
        return PortfolioSample(
            valuation=valuation,
            row={
                EquityField.TIMESTAMP_MS: timestamp_ms,
                EquityField.SAMPLE_REASON: reason.value,
                EquityField.CASH_USDC: decimal_text(valuation.cash_usdc),
                EquityField.MARKED_POSITION_VALUE_USDC: optional_decimal_text(
                    valuation.marked_position_value_usdc
                ),
                EquityField.EQUITY_USDC: optional_decimal_text(valuation.equity_usdc),
                EquityField.PNL_USDC: optional_decimal_text(valuation.pnl_usdc),
                EquityField.FEES_USDC: decimal_text(portfolio.cumulative_fees_usdc),
                EquityField.EXPOSURE_USDC: optional_decimal_text(
                    valuation.exposure_usdc
                ),
                EquityField.POSITION_COUNT: valuation.position_count,
                EquityField.VALUATION_STATUS: valuation.status.value,
            },
        )
