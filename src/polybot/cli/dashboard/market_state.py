"""Book, market-label, settlement, and portfolio state for the dashboard."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from polybot.cli.observability.events import PortfolioSnapshot
from polybot.framework.clock import system_now_ms
from polybot.framework.events import FillEvent
from polybot.framework.events.books import BookSnapshot
from polybot.performance.valuation import PortfolioValuation, value_portfolio

from .token_labels import format_market_label, format_token_label

MARKET_TICKER_INTERVAL_SECONDS = 1


@dataclass(slots=True)
class DashboardMarkets:
    """Owns books and the portfolio marks derived from them."""

    require_accepted_books: bool = False
    book_max_age_ms: int | None = None
    books: dict[str, BookSnapshot] = field(default_factory=dict)
    last_executable_marks: dict[str, Decimal] = field(default_factory=dict)
    market_labels: dict[str, str] = field(default_factory=dict)
    pending_books: dict[str, BookSnapshot] = field(default_factory=dict)
    portfolio: PortfolioSnapshot | None = None
    market_ticker_at_monotonic: dict[str, float] = field(default_factory=dict)
    resolved_condition_ids: set[str] = field(default_factory=set)
    resolved_market_count: int = 0

    def stage_book(self, book: BookSnapshot) -> None:
        self.pending_books[book.token_id] = book

    def record_book(
        self,
        book: BookSnapshot,
        occurred_at_monotonic: float,
        *,
        activate_chart_token: Callable[[str], bool],
        add_market_ticker: Callable[[str, str], None],
    ) -> None:
        if book.condition_id in self.resolved_condition_ids:
            return
        self.books[book.token_id] = book
        if book.market_slug or book.outcome:
            self.market_labels[book.token_id] = format_market_label(
                book.token_id,
                book.market_slug,
                book.outcome,
            )
        activate_chart_token(book.token_id)
        midpoint = book.midpoint()
        previous_ticker_at = self.market_ticker_at_monotonic.get(book.token_id)
        if midpoint is not None and (
            previous_ticker_at is None
            or occurred_at_monotonic - previous_ticker_at
            >= MARKET_TICKER_INTERVAL_SECONDS
        ):
            self.market_ticker_at_monotonic[book.token_id] = occurred_at_monotonic
            add_market_ticker(
                "cyan",
                f"MARKET {format_token_label(book.token_id)} mid {midpoint:.4f}",
            )

    def settle(
        self, *, condition_id: str, token_ids: Iterable[str]
    ) -> tuple[str, ...]:
        if condition_id not in self.resolved_condition_ids:
            self.resolved_condition_ids.add(condition_id)
            self.resolved_market_count += 1
        settled_token_ids = tuple(token_ids)
        for token_id in settled_token_ids:
            self.books.pop(token_id, None)
            self.last_executable_marks.pop(token_id, None)
            self.pending_books.pop(token_id, None)
            self.market_labels.pop(token_id, None)
            self.market_ticker_at_monotonic.pop(token_id, None)
        return settled_token_ids

    def current_book(
        self, token_id: str, now_ms: int | None = None
    ) -> BookSnapshot | None:
        book = self.books.get(token_id)
        if book is None or self.book_max_age_ms is None:
            return book
        current_time_ms = system_now_ms() if now_ms is None else now_ms
        return book if book.is_fresh(current_time_ms, self.book_max_age_ms) else None

    def refresh_fill_mark(self, fill: FillEvent) -> None:
        if self.portfolio is None:
            return
        position = next(
            (
                candidate
                for candidate in self.portfolio.positions
                if candidate.token_id == fill.token_id
            ),
            None,
        )
        if position is None:
            self.last_executable_marks.pop(fill.token_id, None)
            return
        book = self.current_book(fill.token_id, fill.received_at_ms)
        if book is None:
            # Fill telemetry arrives before the corresponding dispatch-completed event.
            pending = self.pending_books.get(fill.token_id)
            if pending is not None and (
                self.book_max_age_ms is None
                or pending.is_fresh(fill.received_at_ms, self.book_max_age_ms)
            ):
                book = pending
        executable_mark = None if book is None else book.executable_mark(position.size)
        if executable_mark is not None:
            self.last_executable_marks[position.token_id] = executable_mark

    def portfolio_valuation(
        self,
        now_ms: int | None,
        *,
        initial_cash_usdc: Decimal | None,
        allow_stale_marks: bool,
    ) -> PortfolioValuation:
        if self.portfolio is None:
            return PortfolioValuation.unavailable()
        result = value_portfolio(
            self.portfolio,
            self.books,
            now_ms=(system_now_ms() if now_ms is None else now_ms),
            max_book_age_ms=self.book_max_age_ms,
            initial_cash_usdc=initial_cash_usdc,
            last_executable_marks=self.last_executable_marks,
            allow_stale_marks=allow_stale_marks,
        )
        self.last_executable_marks = result.marks()
        return result.valuation

    def market_label(self, token_id: str) -> str:
        return self.market_labels.get(token_id, format_token_label(token_id))
