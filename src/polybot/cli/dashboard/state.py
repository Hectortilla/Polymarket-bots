"""In-memory projection of runtime events for terminal rendering."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from math import nan
from time import monotonic, time

from polybot.cli.observability.events import (
    BrokerFailed,
    DispatchCompleted,
    FillCompleted,
    OrderSubmitted,
    PortfolioSnapshot,
    RuntimeEvent,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
    StreamReceived,
)
from polybot.cli.dashboard.palette import SERIES_PALETTE
from polybot.cli.streams import StreamKind
from polybot.framework.events import OrderStatus, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent

MAX_TICKER_ROWS = 40
MAX_CHART_TOKENS = len(SERIES_PALETTE)
EVENT_RATE_WINDOW_SECONDS = 10
MARKET_TICKER_INTERVAL_SECONDS = 1
LATENCY_SAMPLE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class TickerRow:
    style: str
    message: str


@dataclass(slots=True)
class DashboardState:
    name: str = "-"
    mode: str = "-"
    lifecycle: RuntimeState = RuntimeState.STARTING
    started_at: float | None = None
    initial_cash_usdc: Decimal | None = None
    require_accepted_books: bool = False
    book_max_age_ms: int | None = None
    books: dict[str, BookSnapshot] = field(default_factory=dict)
    market_labels: dict[str, str] = field(default_factory=dict)
    pending_books: dict[str, BookSnapshot] = field(default_factory=dict)
    portfolio: PortfolioSnapshot | None = None
    ticker: deque[TickerRow] = field(default_factory=lambda: deque(maxlen=MAX_TICKER_ROWS))
    stream_counts: dict[StreamKind, int] = field(default_factory=dict)
    accepted_dispatches: int = 0
    skipped_dispatches: int = 0
    order_count: int = 0
    fill_count: int = 0
    rejected_count: int = 0
    wallet_detection_lags_ms: deque[int] = field(
        default_factory=lambda: deque(maxlen=LATENCY_SAMPLE_LIMIT)
    )
    broker_latencies_ms: deque[int] = field(
        default_factory=lambda: deque(maxlen=LATENCY_SAMPLE_LIMIT)
    )
    event_times: deque[float] = field(default_factory=deque)
    chart_tokens: deque[str] = field(default_factory=deque)
    price_history: dict[str, deque[float]] = field(default_factory=dict)
    wallet_value_history: deque[float] = field(default_factory=deque)
    market_ticker_at: dict[str, float] = field(default_factory=dict)

    def apply(self, event: RuntimeEvent) -> None:
        self._remember_event(event)
        match event:
            case RuntimeStarted():
                self.name = event.name
                self.mode = event.mode.value
                self.initial_cash_usdc = event.initial_cash_usdc
                self.started_at = event.occurred_at
                self.lifecycle = RuntimeState.STARTING
                self._ticker("bold white", f"Starting {event.name} in {event.mode.value} mode")
            case RuntimeStateChanged():
                self.lifecycle = event.state
                self._ticker("bold yellow", f"Runner {event.state.value}")
            case StreamReceived():
                self._stream_received(event)
            case DispatchCompleted():
                self._dispatch_completed(event)
            case OrderSubmitted():
                self.order_count += 1
                self._ticker(
                    _side_style(event.order.side),
                    f"ORDER {event.order.side.value} {event.order.size} {short_token(event.order.token_id)}",
                )
            case FillCompleted():
                self._fill_completed(event)
            case BrokerFailed():
                self._ticker("bold red", f"BROKER ERROR {event.error}")
            case RuntimeFailed():
                self.lifecycle = RuntimeState.FAILED
                self._ticker("bold red", f"RUN FAILED {event.error}")

    def sample(self, width: int, now_ms: int | None = None) -> None:
        max_points = max(12, min(120, width - 12))
        for token_id in self.chart_tokens:
            history = self.price_history[token_id]
            midpoint = midpoint_for(self._current_book(token_id, now_ms))
            history.append(float(midpoint) if midpoint is not None else nan)
            _trim(history, max_points)
        wallet_value = self.executable_equity(now_ms)
        self.wallet_value_history.append(
            float(wallet_value) if wallet_value is not None else nan
        )
        _trim(self.wallet_value_history, max_points)

    def executable_equity(self, now_ms: int | None = None) -> Decimal | None:
        if self.portfolio is None:
            return None
        equity = self.portfolio.cash_usdc
        for position in self.portfolio.positions:
            book = self._current_book(position.token_id, now_ms)
            mark = executable_mark(book, position.size)
            if mark is None:
                return None
            equity += position.size * mark
        return equity

    def executable_pnl(self, now_ms: int | None = None) -> Decimal | None:
        equity = self.executable_equity(now_ms)
        if equity is None or self.initial_cash_usdc is None:
            return None
        return equity - self.initial_cash_usdc

    def event_rate(self, now: float | None = None) -> float:
        now = monotonic() if now is None else now
        self._trim_event_times(now)
        return len(self.event_times) / EVENT_RATE_WINDOW_SECONDS

    def uptime_seconds(self, now: float | None = None) -> int:
        if self.started_at is None:
            return 0
        return max(0, int((monotonic() if now is None else now) - self.started_at))

    def average_wallet_lag_ms(self) -> int | None:
        return _average(self.wallet_detection_lags_ms)

    def average_broker_latency_ms(self) -> int | None:
        return _average(self.broker_latencies_ms)

    def _remember_event(self, event: RuntimeEvent) -> None:
        occurred_at = getattr(event, "occurred_at", monotonic())
        self.event_times.append(occurred_at)
        self._trim_event_times(occurred_at)

    def _stream_received(self, event: StreamReceived) -> None:
        kind = event.item.kind
        self.stream_counts[kind] = self.stream_counts.get(kind, 0) + 1
        if kind is StreamKind.BOOK:
            if self.require_accepted_books:
                self.pending_books[event.item.event.token_id] = event.item.event
            else:
                self._record_book_stream(event)
        elif kind is StreamKind.WALLET:
            self._record_wallet_stream(event)
        else:
            self._record_market_hint(event)

    def _record_book_stream(self, event: StreamReceived) -> None:
        book = event.item.event
        self.books[book.token_id] = book
        if book.market_slug:
            label = book.market_slug
            if book.outcome:
                label = f"{label} · {book.outcome}"
            self.market_labels[book.token_id] = label
        self._activate_chart_token(book.token_id)
        midpoint = midpoint_for(book)
        last_at = self.market_ticker_at.get(book.token_id)
        if midpoint is not None and (
            last_at is None
            or event.occurred_at - last_at >= MARKET_TICKER_INTERVAL_SECONDS
        ):
            self.market_ticker_at[book.token_id] = event.occurred_at
            self._ticker(
                "cyan",
                f"MARKET {short_token(book.token_id)} mid {midpoint:.4f}",
            )

    def _record_wallet_stream(self, event: StreamReceived) -> None:
        trade = event.item.event
        if isinstance(trade, WalletTradeEvent):
            self.wallet_detection_lags_ms.append(
                trade.observed_at_ms - trade.trade_timestamp_ms
            )
            self._ticker(
                _side_style(trade.side),
                f"FOLLOW {trade.side.value} {trade.size} {short_token(trade.token_id)} @ {trade.price}",
            )

    def _record_market_hint(self, event: StreamReceived) -> None:
        hint = event.item.event
        self._ticker("bright_cyan", f"MARKET HINT {short_token(hint.token_id)}")

    def _dispatch_completed(self, event: DispatchCompleted) -> None:
        if self.require_accepted_books and event.kind is StreamKind.BOOK:
            book = event.item.event
            self.pending_books.pop(book.token_id, None)
            if event.outcome is not None and event.outcome.accepted:
                self._record_book_stream(StreamReceived(event.item, event.occurred_at))
        if event.outcome is None or event.kind is StreamKind.MARKET_HINT:
            return
        if event.outcome.accepted:
            self.accepted_dispatches += 1
            return
        self.skipped_dispatches += 1
        self._ticker("yellow", f"SKIP {event.kind.value}: {event.outcome.skip_reason.value}")

    def _fill_completed(self, event: FillCompleted) -> None:
        self.broker_latencies_ms.append(event.latency_ms)
        self.portfolio = event.portfolio
        fill = event.fill
        if fill.status is OrderStatus.REJECTED:
            self.rejected_count += 1
            self._ticker(
                "bold red",
                f"REJECT {fill.reject_reason.value if fill.reject_reason else 'unknown'}",
            )
            return
        self.fill_count += 1
        price = "-" if fill.average_price is None else str(fill.average_price)
        self._ticker(
            _side_style(fill.side),
            f"FILL {fill.side.value} {fill.filled_size}/{fill.requested_size} {short_token(fill.token_id)} @ {price}",
        )

    def _activate_chart_token(self, token_id: str) -> None:
        if token_id in self.chart_tokens:
            return
        if len(self.chart_tokens) >= MAX_CHART_TOKENS:
            removed = self.chart_tokens.popleft()
            self.price_history.pop(removed, None)
        self.chart_tokens.append(token_id)
        self.price_history.setdefault(token_id, deque())

    def _current_book(self, token_id: str, now_ms: int | None) -> BookSnapshot | None:
        book = self.books.get(token_id)
        if book is None or self.book_max_age_ms is None:
            return book
        current_time_ms = int(time() * 1000) if now_ms is None else now_ms
        return book if book.is_fresh(current_time_ms, self.book_max_age_ms) else None

    def _ticker(self, style: str, message: str) -> None:
        self.ticker.appendleft(TickerRow(style, _safe_message(message)))

    def market_label(self, token_id: str) -> str:
        return self.market_labels.get(token_id, short_token(token_id))

    def _trim_event_times(self, now: float) -> None:
        cutoff = now - EVENT_RATE_WINDOW_SECONDS
        while self.event_times and self.event_times[0] < cutoff:
            self.event_times.popleft()


def midpoint_for(book: BookSnapshot | None) -> Decimal | None:
    bid = _best_bid(book)
    ask = _best_ask(book)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2


def executable_mark(book: BookSnapshot | None, size: Decimal) -> Decimal | None:
    """Mark at the quote required to liquidate a non-zero position."""
    if size > 0:
        return _best_bid(book)
    if size < 0:
        return _best_ask(book)
    return None


def _best_bid(book: BookSnapshot | None) -> Decimal | None:
    if book is None or not book.bids:
        return None
    return max(level.price for level in book.bids)


def _best_ask(book: BookSnapshot | None) -> Decimal | None:
    if book is None or not book.asks:
        return None
    return min(level.price for level in book.asks)


def short_token(token_id: str) -> str:
    return token_id if len(token_id) <= 12 else f"{token_id[:6]}…{token_id[-4:]}"


def _side_style(side: Side) -> str:
    return "bold green" if side is Side.BUY else "bold red"


def _average(values: deque[int]) -> int | None:
    return None if not values else round(sum(values) / len(values))


def _trim(values: deque[float], limit: int) -> None:
    while len(values) > limit:
        values.popleft()


def _safe_message(value: str) -> str:
    return "".join(
        character if character.isprintable() else " "
        for character in value
    )
