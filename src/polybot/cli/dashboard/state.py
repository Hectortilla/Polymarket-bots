"""In-memory projection of runtime events for terminal rendering."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from math import ceil
from time import monotonic, time

from polybot.cli.observability.events import (
    BrokerFailed,
    DispatchCompleted,
    FillCompleted,
    MarketSettled,
    OrderSubmitted,
    PortfolioSnapshot,
    RuntimeEvent,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
    StreamReceived,
    StreamHealth,
)
from polybot.cli.dashboard.palette import SERIES_PALETTE, side_text_style
from polybot.cli.streams.contracts import StreamKind
from polybot.framework.events import OrderStatus, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.config.models import BotMode
from polybot.framework.wallets import normalize_wallet_address

from .copy import (
    RESOLUTION_LOSER_LABEL,
    RESOLUTION_WINNER_LABEL,
    RUN_FAILED_PREFIX,
)
from .chart_state import (
    MAX_CHART_HISTORY_POINTS,
    MAX_CHART_WINDOW_POINTS,
    MAX_TIME_ZOOM_LEVEL,
    MIN_CHART_WINDOW_POINTS,
    MIN_TIME_ZOOM_LEVEL,
    chart_display_points,
    chart_window_points,
    record_sample,
    visible_time_range,
)
from .health import average, ratio
from .token_labels import format_token_label
from .wallet_state import WalletTimelineEvent, wallet_market_label

MAX_TICKER_ROWS = 40
MAX_CHART_TOKENS = len(SERIES_PALETTE)
MAX_WALLET_TIMELINE_EVENTS = 5_000
EVENT_RATE_WINDOW_SECONDS = 10
MARKET_TICKER_INTERVAL_SECONDS = 1
LATENCY_SAMPLE_LIMIT = 100
HEALTH_SAMPLE_LIMIT = 100


@dataclass(frozen=True, slots=True)
class TickerRow:
    style: str
    message: str
    count: int = 1


class DashboardView(StrEnum):
    MARKET = "market"
    WALLET = "wallet"


@dataclass(slots=True)
class DashboardState:
    name: str = "-"
    mode: BotMode | None = None
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
    book_lags_ms: deque[int] = field(default_factory=lambda: deque(maxlen=HEALTH_SAMPLE_LIMIT))
    book_stale_samples: deque[bool] = field(default_factory=lambda: deque(maxlen=HEALTH_SAMPLE_LIMIT))
    book_drop_samples: deque[tuple[int, int]] = field(
        default_factory=lambda: deque(maxlen=HEALTH_SAMPLE_LIMIT)
    )
    book_received_count: int = 0
    book_dropped_count: int = 0
    queue_depth: int = 0
    peak_queue_depth: int = 0
    stream_received_times: dict[StreamKind, deque[float]] = field(default_factory=dict)
    stream_dispatched_times: dict[StreamKind, deque[float]] = field(default_factory=dict)
    event_times: deque[float] = field(default_factory=deque)
    chart_tokens: deque[str] = field(default_factory=deque)
    price_history: dict[str, deque[float]] = field(default_factory=dict)
    price_stale_history: dict[str, deque[bool]] = field(default_factory=dict)
    trade_marker_history: dict[str, deque[tuple[Side, ...]]] = field(default_factory=dict)
    pending_trade_markers: dict[str, list[Side]] = field(default_factory=dict)
    wallet_value_history: deque[float] = field(default_factory=deque)
    wallet_value_stale_history: deque[bool] = field(default_factory=deque)
    chart_sample_times: deque[float] = field(default_factory=deque)
    time_zoom_level: int = 0
    market_ticker_at: dict[str, float] = field(default_factory=dict)
    view: DashboardView = DashboardView.MARKET
    wallet_lanes: deque[str] = field(default_factory=deque)
    wallet_timeline: deque[WalletTimelineEvent] = field(default_factory=deque)
    wallet_timeline_by_source: dict[str, WalletTimelineEvent] = field(default_factory=dict)
    wallet_page: int = 0
    resolved_prices: dict[str, Decimal] = field(default_factory=dict)

    def apply(self, event: RuntimeEvent) -> None:
        self._remember_event(event)
        match event:
            case RuntimeStarted():
                self.name = event.name
                self.mode = event.mode
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
            case StreamHealth():
                self.queue_depth = event.queue_depth
                self.peak_queue_depth = max(self.peak_queue_depth, event.peak_queue_depth)
                self._record_book_drop_counters(event)
                if event.book_dispatch_lag_ms is not None:
                    self.book_lags_ms.append(event.book_dispatch_lag_ms)
                    self.book_stale_samples.append(event.book_stale)
            case OrderSubmitted():
                self.order_count += 1
                self._ticker(
                    _side_style(event.order.side),
                    f"ORDER {event.order.side.value} {event.order.size} {format_token_label(event.order.token_id)}",
                )
            case FillCompleted():
                self._fill_completed(event)
            case BrokerFailed():
                self._ticker("bold red", f"BROKER ERROR {event.error}")
            case MarketSettled():
                self.portfolio = event.portfolio
                self._ticker(
                    "bold magenta",
                    f"SETTLED {event.settlement.resolution.market_slug} paper payout "
                    f"${event.settlement.paper_cash_payout_usdc}",
                )
            case RuntimeFailed():
                self.lifecycle = RuntimeState.FAILED
                self._ticker("bold red", f"{RUN_FAILED_PREFIX} {event.error}")

    def sample(self, width: int, now_ms: int | None = None) -> None:
        record_sample(self, now_ms)

    def chart_window_points(self, width: int) -> int:
        return chart_window_points(self.time_zoom_level, width)

    @staticmethod
    def chart_display_points(width: int) -> int:
        return chart_display_points(width)

    def visible_time_range(self, width: int) -> tuple[float, float] | None:
        return visible_time_range(self.chart_sample_times, self.time_zoom_level, width)

    def zoom_time(self, direction: int) -> bool:
        updated_level = min(
            MAX_TIME_ZOOM_LEVEL,
            max(MIN_TIME_ZOOM_LEVEL, self.time_zoom_level + direction),
        )
        if updated_level == self.time_zoom_level:
            return False
        self.time_zoom_level = updated_level
        return True

    def reset_time_zoom(self) -> bool:
        if self.time_zoom_level == 0:
            return False
        self.time_zoom_level = 0
        return True

    def toggle_view(self) -> None:
        self.view = (
            DashboardView.WALLET
            if self.view is DashboardView.MARKET
            else DashboardView.MARKET
        )
        if self.view is DashboardView.WALLET:
            self.wallet_page = 0

    def page_wallets(self, direction: int, lanes_per_page: int) -> bool:
        if self.view is not DashboardView.WALLET or lanes_per_page <= 0:
            return False
        maximum = max(0, (len(self.wallet_lanes) - 1) // lanes_per_page)
        updated = min(maximum, max(0, self.wallet_page + direction))
        if updated == self.wallet_page:
            return False
        self.wallet_page = updated
        return True

    def set_wallet_lanes(self, wallets: tuple[str, ...]) -> None:
        for wallet in wallets:
            self._activate_wallet_lane(wallet)

    def executable_equity(self, now_ms: int | None = None) -> Decimal | None:
        if self.portfolio is None:
            return None
        equity = self.portfolio.cash_usdc
        for position in self.portfolio.positions:
            book = self._current_book(position.token_id, now_ms)
            mark = None if book is None else book.executable_mark(position.size)
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
        return average(self.wallet_detection_lags_ms)

    def average_broker_latency_ms(self) -> int | None:
        return average(self.broker_latencies_ms)

    def _remember_event(self, event: RuntimeEvent) -> None:
        occurred_at = getattr(event, "occurred_at", monotonic())
        self.event_times.append(occurred_at)
        self._trim_event_times(occurred_at)

    def _stream_received(self, event: StreamReceived) -> None:
        kind = event.item.kind
        self.stream_counts[kind] = self.stream_counts.get(kind, 0) + 1
        self._record_rate(self.stream_received_times, kind, event.occurred_at)
        if kind is StreamKind.BOOK:
            if self.require_accepted_books:
                self.pending_books[event.item.event.token_id] = event.item.event
            else:
                self._record_book_stream(event)
        elif kind is StreamKind.WALLET:
            self._record_wallet_stream(event)
        elif kind is StreamKind.RESOLUTION:
            self._record_resolution(event.item.event)
        else:
            self._record_market_hint(event)

    def _record_resolution(self, event: MarketResolutionEvent) -> None:
        for token_id in event.token_ids:
            self._activate_chart_token(token_id)
            self.resolved_prices[token_id] = event.payout_for(token_id)
            label = self.market_labels.get(token_id, event.market_slug)
            outcome = (
                RESOLUTION_WINNER_LABEL
                if token_id == event.winning_token_id
                else RESOLUTION_LOSER_LABEL
            )
            self.market_labels[token_id] = f"{label} · resolved {outcome}"
            self.pending_books.pop(token_id, None)
        self._ticker(
            "bold magenta",
            f"RESOLVED {event.market_slug}: {event.winning_outcome}",
        )

    def _record_book_stream(self, event: StreamReceived) -> None:
        book = event.item.event
        self.books[book.token_id] = book
        if book.market_slug:
            label = book.market_slug
            if book.outcome:
                label = f"{label} · {book.outcome}"
            self.market_labels[book.token_id] = label
        self._activate_chart_token(book.token_id)
        midpoint = None if book is None else book.midpoint()
        last_at = self.market_ticker_at.get(book.token_id)
        if midpoint is not None and (
            last_at is None
            or event.occurred_at - last_at >= MARKET_TICKER_INTERVAL_SECONDS
        ):
            self.market_ticker_at[book.token_id] = event.occurred_at
            self._ticker(
                "cyan",
                f"MARKET {format_token_label(book.token_id)} mid {midpoint:.4f}",
            )

    def _record_wallet_stream(self, event: StreamReceived) -> None:
        trade = event.item.event
        if isinstance(trade, WalletTradeEvent):
            self._activate_wallet_lane(trade.wallet)
            timeline_event = WalletTimelineEvent(
                source_key=trade.source_key,
                wallet=normalize_wallet_address(trade.wallet),
                trade_timestamp_ms=trade.trade_timestamp_ms,
                side=trade.side,
                notional=trade.price * trade.size,
                market_label=wallet_market_label(trade),
            )
            self.wallet_timeline.append(timeline_event)
            self.wallet_timeline_by_source[trade.source_key] = timeline_event
            while len(self.wallet_timeline) > MAX_WALLET_TIMELINE_EVENTS:
                expired = self.wallet_timeline.popleft()
                if self.wallet_timeline_by_source.get(expired.source_key) is expired:
                    self.wallet_timeline_by_source.pop(expired.source_key, None)
            self.wallet_detection_lags_ms.append(
                trade.observed_at_ms - trade.trade_timestamp_ms
            )
            self._ticker(
                _side_style(trade.side),
                f"FOLLOW {trade.side.value} {trade.size} {wallet_market_label(trade)} @ {trade.price}",
            )

    def _record_market_hint(self, event: StreamReceived) -> None:
        hint = event.item.event
        self._ticker("bright_cyan", f"MARKET HINT {format_token_label(hint.token_id)}")

    def _dispatch_completed(self, event: DispatchCompleted) -> None:
        if self.require_accepted_books and event.kind is StreamKind.BOOK:
            book = event.item.event
            self.pending_books.pop(book.token_id, None)
            if event.outcome is not None and event.outcome.accepted:
                self._record_book_stream(StreamReceived(event.item, event.occurred_at))
        if event.outcome is None or event.kind is StreamKind.MARKET_HINT:
            return
        if event.kind is StreamKind.WALLET and isinstance(event.item.event, WalletTradeEvent):
            timeline_event = self.wallet_timeline_by_source.get(event.item.event.source_key)
            if timeline_event is not None:
                timeline_event.accepted = event.outcome.accepted
        if event.outcome.accepted:
            self.accepted_dispatches += 1
            self._record_rate(self.stream_dispatched_times, event.kind, event.occurred_at)
            return
        self.skipped_dispatches += 1
        self._record_rate(self.stream_dispatched_times, event.kind, event.occurred_at)
        self._ticker("yellow", f"SKIP {event.kind.value}: {event.outcome.skip_reason.value}")

    def stream_rate(self, kind: StreamKind, *, received: bool) -> float:
        samples = (self.stream_received_times if received else self.stream_dispatched_times).get(kind)
        if not samples:
            return 0.0
        now = monotonic()
        self._trim_times(samples, now)
        return len(samples) / EVENT_RATE_WINDOW_SECONDS

    def book_lag_percentile(self, percentile: float) -> int | None:
        if not self.book_lags_ms:
            return None
        values = sorted(self.book_lags_ms)
        index = min(len(values) - 1, max(0, ceil(len(values) * percentile) - 1))
        return values[index]

    def latest_book_lag_ms(self) -> int | None:
        return self.book_lags_ms[-1] if self.book_lags_ms else None

    def maximum_book_lag_ms(self) -> int | None:
        return max(self.book_lags_ms) if self.book_lags_ms else None

    def stale_ratio(self) -> float:
        return ratio(sum(self.book_stale_samples), len(self.book_stale_samples))

    def cumulative_book_drop_ratio(self) -> float:
        return ratio(self.book_dropped_count, self.book_received_count)

    def recent_book_drop_ratio(self) -> float:
        received = sum(sample[0] for sample in self.book_drop_samples)
        return ratio(sum(sample[1] for sample in self.book_drop_samples), received)

    def _record_book_drop_counters(self, event: StreamHealth) -> None:
        if (
            event.book_received_count < self.book_received_count
            or event.book_dropped_count < self.book_dropped_count
        ):
            return
        received_delta = event.book_received_count - self.book_received_count
        dropped_delta = event.book_dropped_count - self.book_dropped_count
        self.book_received_count = event.book_received_count
        self.book_dropped_count = event.book_dropped_count
        if received_delta:
            self.book_drop_samples.append((received_delta, dropped_delta))

    def _record_rate(self, target: dict[StreamKind, deque[float]], kind: StreamKind, occurred_at: float) -> None:
        samples = target.setdefault(kind, deque())
        samples.append(occurred_at)
        self._trim_times(samples, occurred_at)

    @staticmethod
    def _trim_times(samples: deque[float], now: float) -> None:
        cutoff = now - EVENT_RATE_WINDOW_SECONDS
        while samples and samples[0] < cutoff:
            samples.popleft()

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
        if fill.filled_size > 0:
            if self._activate_chart_token(fill.token_id):
                self.pending_trade_markers.setdefault(fill.token_id, []).append(fill.side)
        price = "-" if fill.average_price is None else str(fill.average_price)
        self._ticker(
            _side_style(fill.side),
            f"FILL {fill.side.value} {fill.filled_size}/{fill.requested_size} {format_token_label(fill.token_id)} @ {price}",
        )

    def _activate_chart_token(self, token_id: str) -> bool:
        if token_id in self.chart_tokens:
            return True
        if len(self.chart_tokens) >= MAX_CHART_TOKENS:
            return False
        self.chart_tokens.append(token_id)
        self.price_history.setdefault(token_id, deque())
        self.price_stale_history.setdefault(token_id, deque())
        self.trade_marker_history.setdefault(token_id, deque())
        return True

    def _activate_wallet_lane(self, wallet: str) -> None:
        normalized = normalize_wallet_address(wallet)
        if normalized not in self.wallet_lanes:
            self.wallet_lanes.append(normalized)

    def _current_book(self, token_id: str, now_ms: int | None) -> BookSnapshot | None:
        book = self.books.get(token_id)
        if book is None or self.book_max_age_ms is None:
            return book
        current_time_ms = int(time() * 1000) if now_ms is None else now_ms
        return book if book.is_fresh(current_time_ms, self.book_max_age_ms) else None

    def _ticker(self, style: str, message: str) -> None:
        safe_message = _safe_message(message)
        if self.ticker and self.ticker[0].message == safe_message:
            previous = self.ticker[0]
            self.ticker[0] = TickerRow(previous.style, safe_message, previous.count + 1)
            return
        self.ticker.appendleft(TickerRow(style, safe_message))

    def market_label(self, token_id: str) -> str:
        return self.market_labels.get(token_id, format_token_label(token_id))

    def _trim_event_times(self, now: float) -> None:
        cutoff = now - EVENT_RATE_WINDOW_SECONDS
        while self.event_times and self.event_times[0] < cutoff:
            self.event_times.popleft()


def _side_style(side: Side) -> str:
    return side_text_style(side, bold=True)


def _safe_message(value: str) -> str:
    return "".join(
        character if character.isprintable() else " "
        for character in value
    )
