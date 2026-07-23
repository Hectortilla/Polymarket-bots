"""Coordinator for the terminal dashboard's focused state projections."""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from polybot.cli.observability.events import (
    BrokerFailed,
    BootstrapProgress,
    DispatchCompleted,
    FillCompleted,
    MarketSettled,
    OrderSubmitted,
    PortfolioBookBootstrap,
    PortfolioSnapshot,
    RuntimeEvent,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeState,
    RuntimeStateChanged,
    StreamHealth,
    StreamReceived,
)
from polybot.cli.streams.contracts import StreamKind
from polybot.framework.activity import BotActivityEvent
from polybot.framework.clock import system_now_ms
from polybot.framework.config.models import BotMode
from polybot.framework.events import OrderStatus, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.performance.valuation import PortfolioValuation

from .chart_history import DashboardCharts
from .event_ticker import DashboardTicker, TickerRow
from .market_state import DashboardMarkets
from .runtime_state import DashboardRuntime
from .stream_health import DashboardStreamHealth
from .token_labels import format_token_label
from .view_state import DashboardView, DashboardViewState
from .wallet_state import (
    DashboardWalletTimeline,
    WalletTimelineEvent,
    wallet_market_label,
)


class _ProjectionAttribute:
    """A named façade attribute forwarded to one focused dashboard projection."""

    __slots__ = ("projection", "name")

    def __init__(self, projection: str) -> None:
        self.projection = projection
        self.name = ""

    def __set_name__(self, owner: type[DashboardState], name: str) -> None:
        self.name = name

    def __get__(
        self,
        instance: DashboardState | None,
        owner: type[DashboardState],
    ) -> Any:
        if instance is None:
            return self
        return getattr(getattr(instance, self.projection), self.name)

    def __set__(self, instance: DashboardState, value: Any) -> None:
        setattr(getattr(instance, self.projection), self.name, value)


def _projection_attribute(projection: str) -> Any:
    return _ProjectionAttribute(projection)


class DashboardState:
    """Apply runtime events to the projections consumed by dashboard rendering.

    The façade preserves the aggregate state surface used by renderers and the
    controller, while each projection owns one durable concern. Event routing
    intentionally stays here so callers have one coordination entry point.
    """

    __slots__ = (
        "runtime",
        "markets",
        "ticker_state",
        "stream_health",
        "charts",
        "wallets",
        "view_state",
    )

    # Runtime identity and lifecycle.
    name: str = _projection_attribute("runtime")
    mode: BotMode | None = _projection_attribute("runtime")
    lifecycle: RuntimeState = _projection_attribute("runtime")
    started_at_monotonic: float | None = _projection_attribute("runtime")
    initial_cash_usdc: Decimal | None = _projection_attribute("runtime")

    # Market books, labels, settlement, and portfolio marks.
    require_accepted_books: bool = _projection_attribute("markets")
    book_max_age_ms: int | None = _projection_attribute("markets")
    books: dict[str, BookSnapshot] = _projection_attribute("markets")
    last_executable_marks: dict[str, Decimal] = _projection_attribute("markets")
    market_labels: dict[str, str] = _projection_attribute("markets")
    pending_books: dict[str, BookSnapshot] = _projection_attribute("markets")
    portfolio: PortfolioSnapshot | None = _projection_attribute("markets")
    market_ticker_at_monotonic: dict[str, float] = _projection_attribute("markets")
    resolved_condition_ids: set[str] = _projection_attribute("markets")
    resolved_market_count: int = _projection_attribute("markets")

    # Activity ticker.
    ticker: deque[TickerRow] = _projection_attribute("ticker_state")
    market_ticker: deque[TickerRow] = _projection_attribute("ticker_state")
    show_market_events: bool = _projection_attribute("ticker_state")

    # Stream throughput, dispatch, and latency metrics.
    stream_counts: dict[StreamKind, int] = _projection_attribute("stream_health")
    wallets_loaded: int = _projection_attribute("stream_health")
    wallets_total: int | None = _projection_attribute("stream_health")
    markets_loaded: int = _projection_attribute("stream_health")
    markets_total: int | None = _projection_attribute("stream_health")
    accepted_dispatches: int = _projection_attribute("stream_health")
    skipped_dispatches: int = _projection_attribute("stream_health")
    order_count: int = _projection_attribute("stream_health")
    fill_count: int = _projection_attribute("stream_health")
    rejected_count: int = _projection_attribute("stream_health")
    wallet_detection_lags_ms: deque[int] = _projection_attribute("stream_health")
    broker_latencies_ms: deque[int] = _projection_attribute("stream_health")
    book_lags_ms: deque[int] = _projection_attribute("stream_health")
    book_stale_samples: deque[bool] = _projection_attribute("stream_health")
    book_coalescing_samples: deque[tuple[int, int]] = _projection_attribute(
        "stream_health"
    )
    book_received_count: int = _projection_attribute("stream_health")
    book_coalesced_count: int = _projection_attribute("stream_health")
    queue_depth: int = _projection_attribute("stream_health")
    peak_queue_depth: int = _projection_attribute("stream_health")
    stream_received_monotonic_times: dict[StreamKind, deque[float]] = (
        _projection_attribute("stream_health")
    )
    stream_dispatched_monotonic_times: dict[StreamKind, deque[float]] = (
        _projection_attribute("stream_health")
    )
    event_monotonic_times: deque[float] = _projection_attribute("stream_health")

    # Chart histories and navigation.
    chart_tokens: deque[str] = _projection_attribute("charts")
    price_history: dict[str, deque[float]] = _projection_attribute("charts")
    price_stale_history: dict[str, deque[bool]] = _projection_attribute("charts")
    trade_marker_history: dict[str, deque[tuple[Side, ...]]] = _projection_attribute(
        "charts"
    )
    pending_trade_markers: dict[str, list[Side]] = _projection_attribute("charts")
    wallet_value_history: deque[float] = _projection_attribute("charts")
    wallet_value_stale_history: deque[bool] = _projection_attribute("charts")
    chart_sample_times: deque[float] = _projection_attribute("charts")
    time_zoom_level: int = _projection_attribute("charts")

    # Followed-wallet timeline.
    wallet_lanes: deque[str] = _projection_attribute("wallets")
    wallet_timeline: deque[WalletTimelineEvent] = _projection_attribute("wallets")
    wallet_timeline_by_source: dict[str, WalletTimelineEvent] = _projection_attribute(
        "wallets"
    )
    wallet_page: int = _projection_attribute("wallets")

    # Selected dashboard view.
    view: DashboardView = _projection_attribute("view_state")

    def __init__(
        self,
        *,
        initial_cash_usdc: Decimal | None = None,
        require_accepted_books: bool = False,
        book_max_age_ms: int | None = None,
        chart_tokens: deque[str] | None = None,
        view: DashboardView = DashboardView.MARKET,
    ) -> None:
        self.runtime = DashboardRuntime(initial_cash_usdc=initial_cash_usdc)
        self.markets = DashboardMarkets(
            require_accepted_books=require_accepted_books,
            book_max_age_ms=book_max_age_ms,
        )
        self.ticker_state = DashboardTicker()
        self.stream_health = DashboardStreamHealth()
        self.charts = DashboardCharts(
            chart_tokens=deque(() if chart_tokens is None else chart_tokens)
        )
        self.wallets = DashboardWalletTimeline()
        self.view_state = DashboardViewState(view=view)

    def apply(self, event: RuntimeEvent) -> None:
        """Route a runtime event to its owning state projection."""
        self.stream_health.remember_event(event.occurred_at_monotonic)
        match event:
            case RuntimeStarted():
                self.runtime.start(
                    name=event.name,
                    mode=event.mode,
                    initial_cash_usdc=event.initial_cash_usdc,
                    occurred_at_monotonic=event.occurred_at_monotonic,
                )
                self.ticker_state.add(
                    "bold white",
                    f"Starting {event.name} in {event.mode.value} mode",
                )
            case RuntimeStateChanged():
                self.runtime.transition_to(event.state)
                self.ticker_state.add("bold yellow", f"Runner {event.state.value}")
            case BootstrapProgress():
                self.stream_health.record_bootstrap(
                    event.phase,
                    event.completed,
                    event.total,
                )
            case StreamReceived():
                self._record_stream_received(event)
            case PortfolioBookBootstrap():
                self._record_book(event.book, event.occurred_at_monotonic)
            case DispatchCompleted():
                self._record_dispatch_completed(event)
            case StreamHealth():
                self.stream_health.record_health(
                    queue_depth=event.queue_depth,
                    peak_queue_depth=event.peak_queue_depth,
                    book_dispatch_lag_ms=event.book_dispatch_lag_ms,
                    book_stale=event.book_stale,
                    book_received_count=event.book_received_count,
                    book_coalesced_count=event.book_coalesced_count,
                )
            case OrderSubmitted():
                self.stream_health.record_order()
                self.ticker_state.add(
                    self.ticker_state.side_style(event.order.side),
                    f"ORDER {event.order.side.value} {event.order.size} "
                    f"{self.market_label(event.order.token_id)}",
                )
            case FillCompleted():
                self._record_fill(event)
            case BrokerFailed():
                self.ticker_state.add("bold red", f"BROKER ERROR {event.error}")
            case MarketSettled():
                self.markets.portfolio = event.portfolio
                settled_token_ids = self.markets.settle(
                    condition_id=event.settlement.resolution.condition_id,
                    token_ids=event.settlement.resolution.token_ids,
                )
                self.charts.remove_tokens(settled_token_ids)
            case RuntimeFailed():
                self.runtime.fail()
                self.ticker_state.add("bold red", f"RUN FAILED {event.error}")
            case BotActivityEvent():
                self.ticker_state.add(
                    self.ticker_state.activity_style(event.severity),
                    f"BOT {event.message}",
                )

    def record_chart_sample(self, now_ms: int | None = None) -> None:
        sampled_at_ms = system_now_ms() if now_ms is None else now_ms
        self.charts.record_sample(
            sampled_at_ms,
            current_book=self.markets.current_book,
            executable_equity=self.executable_equity(sampled_at_ms),
        )

    def chart_window_points(self, width: int) -> int:
        return self.charts.chart_window_points(width)

    @staticmethod
    def chart_display_points(width: int) -> int:
        return DashboardCharts.chart_display_points(width)

    def visible_time_range(self, width: int) -> tuple[float, float] | None:
        return self.charts.visible_time_range(width)

    def zoom_time(self, direction: int) -> bool:
        return self.charts.zoom(direction)

    def reset_time_zoom(self) -> bool:
        return self.charts.reset_zoom()

    def toggle_view(self) -> None:
        if self.view_state.toggle() is DashboardView.WALLET:
            self.wallets.reset_page()

    def toggle_market_events(self) -> None:
        self.ticker_state.toggle_market_events()

    def page_wallets(self, direction: int, lanes_per_page: int) -> bool:
        if self.view is not DashboardView.WALLET:
            return False
        return self.wallets.page(direction, lanes_per_page)

    def revalidate_wallet_page(self, lanes_per_page: int) -> bool:
        return self.wallets.revalidate_page(lanes_per_page)

    def set_wallet_lanes(self, wallets: tuple[str, ...]) -> None:
        self.wallets.set_lanes(wallets)

    def executable_equity(self, now_ms: int | None = None) -> Decimal | None:
        return self._portfolio_valuation(now_ms, allow_stale_marks=False).equity_usdc

    def executable_pnl(self, now_ms: int | None = None) -> Decimal | None:
        return self._portfolio_valuation(now_ms, allow_stale_marks=False).pnl_usdc

    def portfolio_valuation(self, now_ms: int | None = None) -> PortfolioValuation:
        """Value unavailable positions at their last executable mark for display."""
        return self._portfolio_valuation(now_ms, allow_stale_marks=True)

    def event_rate(self, now_monotonic: float | None = None) -> float:
        return self.stream_health.event_rate(now_monotonic)

    def uptime_seconds(self, now_monotonic: float | None = None) -> int:
        return self.runtime.uptime_seconds(now_monotonic)

    def average_wallet_lag_ms(self) -> int | None:
        return self.stream_health.average_wallet_lag_ms()

    def average_broker_latency_ms(self) -> int | None:
        return self.stream_health.average_broker_latency_ms()

    def stream_rate(self, kind: StreamKind, *, received: bool) -> float:
        return self.stream_health.stream_rate(kind, received=received)

    def latest_book_lag_ms(self) -> int | None:
        return self.stream_health.latest_book_lag_ms()

    def book_lag_percentile(self, percentile: float) -> int | None:
        return self.stream_health.book_lag_percentile(percentile)

    def maximum_book_lag_ms(self) -> int | None:
        return self.stream_health.maximum_book_lag_ms()

    def stale_ratio(self) -> float:
        return self.stream_health.stale_ratio()

    def cumulative_book_coalescing_ratio(self) -> float:
        return self.stream_health.cumulative_book_coalescing_ratio()

    def recent_book_coalescing_ratio(self) -> float:
        return self.stream_health.recent_book_coalescing_ratio()

    def activity_ticker(self) -> list[TickerRow]:
        return self.ticker_state.rows()

    def market_label(self, token_id: str) -> str:
        return self.markets.market_label(token_id)

    def _record_stream_received(self, event: StreamReceived) -> None:
        kind = event.item.kind
        self.stream_health.record_stream_received(kind, event.occurred_at_monotonic)
        if kind is StreamKind.BOOK:
            book = event.item.event
            if self.markets.require_accepted_books:
                self.markets.stage_book(book)
            else:
                self._record_book(book, event.occurred_at_monotonic)
            return
        if kind is StreamKind.WALLET:
            trade = event.item.event
            if isinstance(trade, WalletTradeEvent):
                self.wallets.record_trade(trade)
                self.stream_health.record_wallet_detection_lag(
                    trade.observed_at_ms - trade.trade_timestamp_ms
                )
                self.ticker_state.add(
                    self.ticker_state.side_style(trade.side),
                    f"FOLLOW {trade.side.value} {trade.size} "
                    f"{wallet_market_label(trade)} @ {trade.price}",
                )
            return
        if kind is StreamKind.MARKET_HINT:
            hint = event.item.event
            self.ticker_state.add_market_event(
                "bright_cyan",
                f"MARKET HINT {format_token_label(hint.token_id)}",
            )

    def _record_book(self, book: BookSnapshot, occurred_at_monotonic: float) -> None:
        self.markets.record_book(
            book,
            occurred_at_monotonic,
            activate_chart_token=self.charts.activate_token,
            add_market_ticker=self.ticker_state.add_market_event,
        )

    def _record_dispatch_completed(self, event: DispatchCompleted) -> None:
        if self.markets.require_accepted_books and event.kind is StreamKind.BOOK:
            book = event.item.event
            self.markets.pending_books.pop(book.token_id, None)
            if event.outcome is not None and event.outcome.accepted:
                self._record_book(book, event.occurred_at_monotonic)
        if event.outcome is None or event.kind is StreamKind.MARKET_HINT:
            return
        if event.kind is StreamKind.WALLET and isinstance(
            event.item.event, WalletTradeEvent
        ):
            self.wallets.mark_dispatch(
                event.item.event.source_key,
                accepted=event.outcome.accepted,
            )
        self.stream_health.record_dispatch(
            event.kind,
            accepted=event.outcome.accepted,
            occurred_at_monotonic=event.occurred_at_monotonic,
        )
        if not event.outcome.accepted:
            self.ticker_state.add(
                "yellow",
                f"SKIP {event.kind.value}: {event.outcome.skip_reason.value}",
            )

    def _record_fill(self, event: FillCompleted) -> None:
        fill = event.fill
        is_rejected = fill.status is OrderStatus.REJECTED
        self.stream_health.record_fill(event.latency_ms, rejected=is_rejected)
        self.markets.portfolio = event.portfolio
        if is_rejected:
            self.ticker_state.add(
                "bold red",
                "REJECT "
                f"{fill.reject_reason.value if fill.reject_reason else 'unknown'}",
            )
            return
        self.markets.refresh_fill_mark(fill)
        if fill.filled_size > 0:
            self.charts.record_trade(fill.token_id, fill.side)
        price = "-" if fill.average_price is None else str(fill.average_price)
        self.ticker_state.add(
            self.ticker_state.side_style(fill.side),
            f"FILL {fill.side.value} {fill.filled_size}/{fill.requested_size} "
            f"{self.market_label(fill.token_id)} @ {price}",
        )

    def _portfolio_valuation(
        self,
        now_ms: int | None,
        *,
        allow_stale_marks: bool,
    ) -> PortfolioValuation:
        return self.markets.portfolio_valuation(
            now_ms,
            initial_cash_usdc=self.runtime.initial_cash_usdc,
            allow_stale_marks=allow_stale_marks,
        )
