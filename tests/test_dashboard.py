import asyncio
from collections import deque
from datetime import datetime
from decimal import Decimal
from io import StringIO
from math import inf, isnan, nan
from threading import Event, Thread

import asciichartpy
import pytest
from rich.console import Console

from polybot.async_io import run_blocking
from polybot.cli.charting import (
    padded_value_bounds,
    render_chart,
    resample_indices,
)
from polybot.cli.dashboard.render import (
    PRICE_CHART_MAX,
    PRICE_CHART_MIN,
    _chart_time_range,
    _fixed_ms,
    _price_chart_height,
    _price_chart_series,
    _wallet_bucket_glyph,
    _wallet_timeline_buckets,
    render_dashboard,
)
from polybot.cli.dashboard.controller import TerminalDashboard
from polybot.cli.dashboard.status import filled_progress_width, optional_money
from polybot.cli.dashboard.chart_history import (
    MAX_CHART_HISTORY_POINTS,
    MAX_CHART_TOKENS,
)
from polybot.cli.dashboard.state import DashboardState
from polybot.cli.dashboard.view_state import DashboardView
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.activity import ActivitySeverity, BotActivityEvent
from polybot.cli.observability.broker import ObservableBroker
from polybot.cli.observability.events import (
    BrokerFailed,
    BootstrapPhase,
    BootstrapProgress,
    DispatchCompleted,
    FillCompleted,
    MarketSettled,
    OrderSubmitted,
    PortfolioPositionSnapshot,
    PortfolioBookBootstrap,
    PortfolioSnapshot,
    RuntimeFailed,
    RuntimeStarted,
    StreamReceived,
    StreamHealth,
)
from polybot.cli.observability.bootstrap import emit_paper_position_book_bootstraps
from polybot.cli.observability.observer import (
    RuntimeObserver,
    emit_observer,
    start_observer,
    stop_observer,
)
from polybot.cli.streams.contracts import (
    BookStreamEvent,
    MarketHintStreamEvent,
    StreamKind,
    WalletStreamEvent,
)
from polybot.framework.config.models import BotConfig
from polybot.framework.events import FillEvent, FillRejectReason, OrderRequest, OrderStatus, Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
)
from polybot.framework.outcomes import YES_OUTCOME
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.polymarket.market_hints import MarketTradeHint


class RecordingObserver(RuntimeObserver):
    def __init__(self) -> None:
        self.events = []

    async def start(self, config: BotConfig) -> None:
        return None

    def emit(self, event) -> None:
        self.events.append(event)

    async def stop(self) -> None:
        return None


class FailingObserver(RuntimeObserver):
    async def start(self, config: BotConfig) -> None:
        raise RuntimeError("start failed")

    def emit(self, event) -> None:
        raise RuntimeError("emit failed")

    async def stop(self) -> None:
        raise RuntimeError("stop failed")


def test_observer_failures_are_suppressed() -> None:
    async def run() -> None:
        observer = FailingObserver()
        await start_observer(observer, BotConfig(name="failing-observer"))
        emit_observer(observer, RuntimeStarted.from_config(BotConfig(name="failing-observer")))
        await stop_observer(observer)

    asyncio.run(run())


def test_dashboard_start_does_not_block_the_event_loop(monkeypatch) -> None:
    started = Event()
    release = Event()

    class BlockingLive:
        def __init__(self, **kwargs) -> None:
            self.stopped = False

        def start(self, *, refresh: bool) -> None:
            started.set()
            release.wait(timeout=1)

        def update(self, renderable, *, refresh: bool) -> None:
            return None

        def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr("polybot.cli.dashboard.controller.Live", BlockingLive)

    async def run() -> bool:
        dashboard = TerminalDashboard(Console(width=80, height=24))
        start_task = asyncio.create_task(dashboard.start(BotConfig(name="dashboard")))
        await run_blocking(started.wait, 1)
        scheduled = False

        async def schedule() -> None:
            nonlocal scheduled
            await asyncio.sleep(0)
            scheduled = True

        await schedule()
        release.set()
        await start_task
        await dashboard.stop()
        return scheduled

    assert asyncio.run(run())


def test_dashboard_render_is_threaded_and_stop_closes_live_session(monkeypatch) -> None:
    update_started = Event()
    release_update = Event()
    live_sessions = []

    class BlockingLive:
        def __init__(self, **kwargs) -> None:
            self.raise_on_update = False
            self.stopped = False
            live_sessions.append(self)

        def start(self, *, refresh: bool) -> None:
            return None

        def update(self, renderable, *, refresh: bool) -> None:
            update_started.set()
            release_update.wait(timeout=1)
            if self.raise_on_update:
                raise RuntimeError("render failed")

        def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr("polybot.cli.dashboard.controller.Live", BlockingLive)

    async def run() -> bool:
        dashboard = TerminalDashboard(Console(width=80, height=24))
        await dashboard.start(BotConfig(name="dashboard"))
        dashboard.emit(RuntimeStarted.from_config(BotConfig(name="dashboard")))
        await run_blocking(update_started.wait, 1)
        scheduled = False

        async def schedule() -> None:
            nonlocal scheduled
            await asyncio.sleep(0)
            scheduled = True

        await schedule()
        release_update.set()
        await asyncio.sleep(0)
        live_sessions[0].raise_on_update = True
        with pytest.raises(RuntimeError, match="render failed"):
            await dashboard.stop()
        return scheduled

    assert asyncio.run(run())
    assert live_sessions[0].stopped


def test_dashboard_stop_waits_for_terminal_reader_cleanup() -> None:
    reader_finished = Event()
    reader_cancelled = Event()

    class LiveSession:
        def update(self, renderable, *, refresh: bool) -> None:
            return None

        def stop(self) -> None:
            return None

    async def run() -> None:
        dashboard = TerminalDashboard(Console(width=80, height=24))
        dashboard._live = LiveSession()

        async def reader() -> None:
            try:
                while not dashboard._input_stop.is_set():
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                reader_cancelled.set()
                raise
            reader_finished.set()

        dashboard._input_task = asyncio.create_task(reader())
        await dashboard.stop()

    asyncio.run(run())

    assert reader_finished.is_set()
    assert not reader_cancelled.is_set()


def test_dashboard_reports_render_loop_failure(monkeypatch) -> None:
    stopped = Event()
    output = StringIO()

    class FailingLive:
        def __init__(self, **kwargs) -> None:
            return None

        def start(self, *, refresh: bool) -> None:
            return None

        def update(self, renderable, *, refresh: bool) -> None:
            raise RuntimeError("chart exploded")

        def stop(self) -> None:
            stopped.set()

    monkeypatch.setattr("polybot.cli.dashboard.controller.Live", FailingLive)

    async def inline_to_thread(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "polybot.cli.dashboard.controller.run_blocking",
        inline_to_thread,
    )

    async def run() -> None:
        dashboard = TerminalDashboard(
            Console(file=output, width=80, height=24, force_terminal=False)
        )
        await dashboard.start(BotConfig(name="dashboard"))
        dashboard.emit(RuntimeStarted.from_config(BotConfig(name="dashboard")))
        await asyncio.sleep(0)
        assert stopped.is_set()
        await dashboard.stop()

    asyncio.run(run())

    rendered_output = output.getvalue()
    assert "Dashboard stopped after an internal error" in rendered_output
    assert "RuntimeError: chart exploded" in rendered_output


def test_dashboard_releases_state_lock_before_terminal_update() -> None:
    update_started = Event()
    release_update = Event()

    class BlockingLive:
        def update(self, renderable, *, refresh: bool) -> None:
            update_started.set()
            release_update.wait(timeout=1)

    dashboard = TerminalDashboard(Console(width=80, height=24))
    dashboard._live = BlockingLive()
    render_thread = Thread(target=dashboard._render)

    render_thread.start()
    assert update_started.wait(timeout=1)
    dashboard.emit(RuntimeStarted.from_config(BotConfig(name="dashboard")))
    release_update.set()
    render_thread.join(timeout=1)

    assert not render_thread.is_alive()


def test_dashboard_marks_long_at_bid_and_short_at_ask() -> None:
    state = DashboardState()
    state.apply(RuntimeStarted.from_config(BotConfig(name="dashboard")))
    state.books["long"] = _book("long", Decimal("0.40"), Decimal("0.60"))
    state.books["short"] = _book("short", Decimal("0.20"), Decimal("0.30"))
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("100"),
        cumulative_fees_usdc=Decimal("1"),
        positions=(
            PortfolioPositionSnapshot("long", Decimal("2"), Decimal("0.50")),
            PortfolioPositionSnapshot("short", Decimal("-3"), Decimal("0.25")),
        ),
    )

    assert state.executable_equity() == Decimal("99.90")
    assert state.executable_pnl() == Decimal("-900.10")


def test_dashboard_pnl_is_unavailable_when_position_cannot_be_marked() -> None:
    state = DashboardState(initial_cash_usdc=Decimal("100"))
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("missing", Decimal("1"), Decimal("0.50")),),
    )

    assert state.executable_equity() is None
    assert state.executable_pnl() is None


def test_dashboard_uses_last_executable_mark_while_waiting_for_resolution() -> None:
    state = DashboardState(book_max_age_ms=100, initial_cash_usdc=Decimal("100"))
    state.books["closed"] = _book(
        "closed",
        Decimal("0.40"),
        Decimal("0.60"),
        received_at_ms=1_000,
    )
    state.books["active"] = _book(
        "active",
        Decimal("0.30"),
        Decimal("0.50"),
        received_at_ms=1_000,
    )
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(
            PortfolioPositionSnapshot("closed", Decimal("1"), Decimal("0.50")),
            PortfolioPositionSnapshot("active", Decimal("2"), Decimal("0.40")),
        ),
    )

    assert state.executable_equity(now_ms=1_000) == Decimal("91.00")
    state.books["active"] = _book(
        "active",
        Decimal("0.30"),
        Decimal("0.50"),
        received_at_ms=1_200,
    )
    valuation = state.portfolio_valuation(now_ms=1_200)

    assert valuation.equity_usdc == Decimal("91.00")
    assert valuation.pnl_usdc == Decimal("-9.00")
    assert valuation.is_stale is True
    assert state.executable_equity(now_ms=1_200) is None
    assert (
        optional_money(valuation.equity_usdc, stale=valuation.is_stale)
        == "$91.00 (stale)"
    )
    assert (
        optional_money(valuation.pnl_usdc, stale=valuation.is_stale)
        == "$-9.00 (stale)"
    )


def test_dashboard_reuses_stale_mark_after_position_size_changes() -> None:
    state = DashboardState(book_max_age_ms=100)
    state.books["token"] = _book(
        "token",
        Decimal("0.40"),
        Decimal("0.60"),
        received_at_ms=1_000,
    )
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("token", Decimal("1"), Decimal("0.50")),),
    )
    assert state.executable_equity(now_ms=1_000) == Decimal("90.40")
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("80"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("token", Decimal("2"), Decimal("0.50")),),
    )

    valuation = state.portfolio_valuation(now_ms=1_101)

    assert valuation.equity_usdc == Decimal("80.80")
    assert valuation.is_stale is True


def test_dashboard_refreshes_stale_mark_for_new_position_size_after_fill() -> None:
    state = DashboardState(book_max_age_ms=100)
    state.books["token"] = _book(
        "token",
        Decimal("0.40"),
        Decimal("0.60"),
        received_at_ms=1_000,
    )
    fill = FillEvent(
        order_id="order",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("2"),
        filled_size=Decimal("2"),
        average_price=Decimal("0.50"),
        fee_usdc=Decimal("0"),
        received_at_ms=1_050,
    )
    state.apply(
        FillCompleted(
            OrderRequest("token", Side.BUY, Decimal("0.50"), Decimal("2")),
            fill,
            PortfolioSnapshot(
                cash_usdc=Decimal("89"),
                cumulative_fees_usdc=Decimal("0"),
                positions=(
                    PortfolioPositionSnapshot("token", Decimal("2"), Decimal("0.50")),
                ),
            ),
            latency_ms=1,
            occurred_at_monotonic=1.0,
        )
    )
    state.books.clear()

    valuation = state.portfolio_valuation(now_ms=1_051)

    assert valuation.equity_usdc == Decimal("89.80")
    assert valuation.is_stale is True


def test_dashboard_refreshes_fill_mark_from_pending_book() -> None:
    state = DashboardState(require_accepted_books=True, book_max_age_ms=100)
    book = _book(
        "token",
        Decimal("0.40"),
        Decimal("0.60"),
        received_at_ms=1_000,
    )
    item = BookStreamEvent(StreamKind.BOOK, book)
    state.apply(StreamReceived(item, 1.0))
    fill = FillEvent(
        order_id="order",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("2"),
        filled_size=Decimal("2"),
        average_price=Decimal("0.50"),
        fee_usdc=Decimal("0"),
        received_at_ms=1_050,
    )
    state.apply(
        FillCompleted(
            OrderRequest("token", Side.BUY, Decimal("0.50"), Decimal("2")),
            fill,
            PortfolioSnapshot(
                cash_usdc=Decimal("89"),
                cumulative_fees_usdc=Decimal("0"),
                positions=(
                    PortfolioPositionSnapshot("token", Decimal("2"), Decimal("0.50")),
                ),
            ),
            latency_ms=1,
            occurred_at_monotonic=1.0,
        )
    )
    state.pending_books.clear()

    valuation = state.portfolio_valuation(now_ms=1_051)

    assert valuation.equity_usdc == Decimal("89.80")
    assert valuation.is_stale is True


def test_dashboard_keeps_chart_selection_stable_when_markets_exceed_capacity() -> None:
    assert MAX_CHART_TOKENS == 20

    state = DashboardState()
    for pass_index in range(2):
        for index in range(MAX_CHART_TOKENS + 1):
            token_id = f"token-{index}"
            state.apply(
                StreamReceived(
                    BookStreamEvent(
                        StreamKind.BOOK,
                        _book(token_id, Decimal("0.4"), Decimal("0.6")),
                    ),
                    float(pass_index * (MAX_CHART_TOKENS + 1) + index),
                )
            )
        state.record_chart_sample()
    trade = WalletTradeEvent(
        wallet="0xleader",
        condition_id="condition",
        token_id="token-4",
        side=Side.BUY,
        size=Decimal("2"),
        price=Decimal("0.50"),
        source_id="trade",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_125,
    )
    state.apply(StreamReceived(WalletStreamEvent(StreamKind.WALLET, trade), 6.0))

    expected_tokens = tuple(
        f"token-{index}"
        for index in range(MAX_CHART_TOKENS)
    )
    assert tuple(state.chart_tokens) == expected_tokens
    assert state.average_wallet_lag_ms() == 125
    assert state.stream_counts[StreamKind.BOOK] == 2 * (MAX_CHART_TOKENS + 1)
    assert state.stream_counts[StreamKind.WALLET] == 1
    assert set(state.price_history) == set(expected_tokens)
    assert all(len(values) == 2 for values in state.price_history.values())


def test_dashboard_renders_all_twenty_chart_series() -> None:
    state = DashboardState()
    for index in range(MAX_CHART_TOKENS):
        state.apply(
            StreamReceived(
                BookStreamEvent(
                    StreamKind.BOOK,
                    _book(f"token-{index}", Decimal("0.4"), Decimal("0.6")),
                ),
                float(index),
            )
        )
    state.record_chart_sample()

    render_dashboard(state, 160, 40)

    assert len(state.chart_tokens) == MAX_CHART_TOKENS


def test_dashboard_tracks_stream_health_samples() -> None:
    state = DashboardState()
    state.apply(StreamHealth(3, 9, 120, False, 1.0))
    state.apply(StreamHealth(5, 12, 6_100, True, 2.0))

    assert state.queue_depth == 5
    assert state.peak_queue_depth == 12
    assert state.latest_book_lag_ms() == 6_100
    assert state.book_lag_percentile(0.95) == 6_100
    assert state.maximum_book_lag_ms() == 6_100
    assert state.stale_ratio() == 0.5


def test_dashboard_tracks_and_renders_bootstrap_progress() -> None:
    state = DashboardState()
    state.apply(BootstrapProgress(BootstrapPhase.WALLETS, 2, 5, 1.0))
    state.apply(BootstrapProgress(BootstrapPhase.MARKETS, 7, 10, 2.0))

    assert (state.wallets_loaded, state.wallets_total) == (2, 5)
    assert (state.markets_loaded, state.markets_total) == (7, 10)

    output = StringIO()
    Console(file=output, width=80, height=24).print(render_dashboard(state, 80, 24))

    rendered = output.getvalue()
    assert BootstrapPhase.WALLETS.value in rendered and "2/5" in rendered
    assert BootstrapPhase.MARKETS.value in rendered and "7/10" in rendered


def test_dashboard_progress_width_handles_empty_partial_and_complete() -> None:
    assert filled_progress_width(0, 0, bar_width=12) == 0
    assert filled_progress_width(2, 5, bar_width=12) == 4
    assert filled_progress_width(5, 5, bar_width=12) == 12


def test_dashboard_formats_book_lag_with_stable_width() -> None:
    assert _fixed_ms(9) == "     9ms"
    assert _fixed_ms(12_345) == " 12345ms"
    assert _fixed_ms(None) == "     N/A"


def test_dashboard_tracks_cumulative_and_recent_book_coalescing_ratios() -> None:
    state = DashboardState()
    assert state.cumulative_book_coalescing_ratio() == 0.0
    assert state.recent_book_coalescing_ratio() == 0.0

    state.apply(
        StreamHealth(
            1,
            3,
            10,
            book_received_count=10,
            book_coalesced_count=2,
        )
    )
    state.apply(
        StreamHealth(
            0,
            3,
            12,
            book_received_count=15,
            book_coalesced_count=4,
        )
    )

    assert state.book_received_count == 15
    assert state.book_coalesced_count == 4
    assert state.cumulative_book_coalescing_ratio() == pytest.approx(4 / 15)
    assert state.recent_book_coalescing_ratio() == pytest.approx(4 / 15)


def test_dashboard_recent_book_coalescing_ratio_uses_last_100_book_deltas() -> None:
    state = DashboardState()
    received = 0
    dropped = 0
    for index in range(101):
        received += 1
        dropped += int(index == 0 or index == 100)
        state.apply(
            StreamHealth(
                0,
                1,
                None,
                book_received_count=received,
                book_coalesced_count=dropped,
            )
        )

    assert state.cumulative_book_coalescing_ratio() == pytest.approx(2 / 101)
    assert state.recent_book_coalescing_ratio() == pytest.approx(1 / 100)


def test_dashboard_ignores_non_book_health_samples_for_recent_drop_window() -> None:
    state = DashboardState()
    state.apply(StreamHealth(0, 1, None, book_received_count=2, book_coalesced_count=1))
    for _ in range(150):
        state.apply(StreamHealth(0, 1, None, book_received_count=2, book_coalesced_count=1))

    assert list(state.book_coalescing_samples) == [(2, 1)]
    assert state.recent_book_coalescing_ratio() == 0.5


def test_dashboard_keeps_chart_series_order_stable_on_book_updates() -> None:
    state = DashboardState()
    first = StreamReceived(
        BookStreamEvent(StreamKind.BOOK, _book("first", Decimal("0.4"), Decimal("0.6"))),
        1.0,
    )
    second = StreamReceived(
        BookStreamEvent(StreamKind.BOOK, _book("second", Decimal("0.3"), Decimal("0.7"))),
        2.0,
    )

    state.apply(first)
    state.apply(second)
    state.apply(StreamReceived(first.item, 3.0))

    assert tuple(state.chart_tokens) == ("first", "second")


def test_dashboard_uses_market_slug_for_chart_labels() -> None:
    state = DashboardState()
    book = _book("token", Decimal("0.4"), Decimal("0.6"))
    state.apply(
        StreamReceived(
            BookStreamEvent(
                StreamKind.BOOK,
                BookSnapshot(
                    token_id=book.token_id,
                    bids=book.bids,
                    asks=book.asks,
                    received_at_ms=book.received_at_ms,
                    market_slug="btc-up-or-down",
                    outcome=YES_OUTCOME,
                ),
            ),
            1.0,
        )
    )

    assert state.market_label("token") == "btc-up-or-down · Yes"
    assert state.market_label("unknown-token") == "unknown…oken"


def test_dashboard_hides_market_activity_by_default_and_labels_orders_and_fills() -> None:
    state = DashboardState()
    book = _book("blue-token", Decimal("0.4"), Decimal("0.6"))
    state.apply(
        StreamReceived(
            BookStreamEvent(
                StreamKind.BOOK,
                BookSnapshot(
                    token_id=book.token_id,
                    bids=book.bids,
                    asks=book.asks,
                    received_at_ms=book.received_at_ms,
                    market_slug="btc-up-or-down",
                    outcome=YES_OUTCOME,
                ),
            ),
            1.0,
        )
    )
    state.apply(
        StreamReceived(
            MarketHintStreamEvent(
                StreamKind.MARKET_HINT,
                MarketTradeHint("condition", "hint-token", "market", 1),
            ),
            1.5,
        )
    )
    order = OrderRequest("blue-token", Side.BUY, Decimal("0.5"), Decimal("2"))
    fill = FillEvent(
        order_id="order",
        token_id="blue-token",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("2"),
        filled_size=Decimal("2"),
        average_price=Decimal("0.5"),
        fee_usdc=Decimal("0"),
        received_at_ms=1,
    )
    state.apply(OrderSubmitted(order, 2.0))
    state.apply(FillCompleted(order, fill, None, 1, 3.0))

    assert state.ticker[1].message == "ORDER BUY 2 btc-up-or-down · Yes"
    assert state.ticker[0].message == "FILL BUY 2/2 btc-up-or-down · Yes @ 0.5"
    assert state.market_ticker[0].message == "MARKET HINT hint-token"
    assert state.market_ticker[1].message == "MARKET blue-token mid 0.5000"
    assert [row.message for row in state.activity_ticker()] == [
        "FILL BUY 2/2 btc-up-or-down · Yes @ 0.5",
        "ORDER BUY 2 btc-up-or-down · Yes",
    ]

    hidden_output = StringIO()
    Console(file=hidden_output, width=120, height=35).print(render_dashboard(state, 120, 35))
    assert "Activity · m: market off" in hidden_output.getvalue()
    assert "MARKET blue-token" not in hidden_output.getvalue()
    assert "MARKET HINT hint-token" not in hidden_output.getvalue()

    state.toggle_market_events()

    shown_output = StringIO()
    Console(file=shown_output, width=120, height=35).print(render_dashboard(state, 120, 35))
    assert "Activity · m: market on" in shown_output.getvalue()
    assert "MARKET blue-token mid 0.5000" in shown_output.getvalue()
    assert "MARKET HINT hint-token" in shown_output.getvalue()


def test_dashboard_m_key_toggles_market_activity() -> None:
    dashboard = TerminalDashboard(Console(width=80, height=24))

    dashboard._handle_key("m")

    assert dashboard._state.show_market_events


def test_dashboard_renders_bot_activity_with_severity_and_safe_message() -> None:
    state = DashboardState()
    state.apply(
        BotActivityEvent(
            "trigger\nconfirmed",
            severity=ActivitySeverity.WARNING,
            occurred_at_monotonic=1.0,
        )
    )

    row = state.activity_ticker()[0]

    assert row.message == "BOT trigger confirmed"
    assert row.style == "bold yellow"


def test_observable_broker_returns_original_fill_and_emits_order_then_fill() -> None:
    class Broker:
        async def submit(self, order: OrderRequest) -> FillEvent:
            return FillEvent(
                order_id="order",
                token_id=order.token_id,
                side=order.side,
                status=OrderStatus.FILLED,
                requested_size=order.size,
                filled_size=order.size,
                average_price=order.price,
                fee_usdc=Decimal("0"),
                received_at_ms=1,
            )

        async def cancel_all(self) -> None:
            return None

    async def run():
        observer = RecordingObserver()
        broker = ObservableBroker(
            Broker(),
            observer,
            lambda: PortfolioSnapshot(Decimal("99"), Decimal("1"), ()),
        )
        fill = await broker.submit(
            OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("1"))
        )
        return fill, observer.events

    fill, events = asyncio.run(run())
    assert fill.status is OrderStatus.FILLED
    assert isinstance(events[0], OrderSubmitted)
    assert isinstance(events[1], FillCompleted)
    assert events[1].portfolio is not None


def test_observable_broker_preserves_broker_failure() -> None:
    class FailingBroker:
        async def submit(self, order: OrderRequest) -> FillEvent:
            raise RuntimeError("broker unavailable")

        async def cancel_all(self) -> None:
            return None

    async def run() -> list[object]:
        observer = RecordingObserver()
        broker = ObservableBroker(FailingBroker(), observer, lambda: None)
        with pytest.raises(RuntimeError, match="broker unavailable"):
            await broker.submit(OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("1")))
        return observer.events

    events = asyncio.run(run())
    assert isinstance(events[0], OrderSubmitted)
    assert isinstance(events[1], BrokerFailed)


def test_observable_broker_ignores_portfolio_snapshot_failure() -> None:
    class Broker:
        async def submit(self, order: OrderRequest) -> FillEvent:
            return FillEvent(
                order_id="order",
                token_id=order.token_id,
                side=order.side,
                status=OrderStatus.FILLED,
                requested_size=order.size,
                filled_size=order.size,
                average_price=order.price,
                fee_usdc=Decimal("0"),
                received_at_ms=1,
            )

        async def cancel_all(self) -> None:
            return None

    async def run() -> tuple[FillEvent, list[object]]:
        observer = RecordingObserver()
        broker = ObservableBroker(
            Broker(),
            observer,
            lambda: (_ for _ in ()).throw(RuntimeError("snapshot unavailable")),
        )
        fill = await broker.submit(OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("1")))
        return fill, observer.events

    fill, events = asyncio.run(run())
    assert fill.status is OrderStatus.FILLED
    assert isinstance(events[1], FillCompleted)
    assert events[1].portfolio is None


def test_dashboard_skips_rejected_books_but_counts_them() -> None:
    state = DashboardState(require_accepted_books=True)
    rejected_book = _book("rejected", Decimal("0.60"), Decimal("0.40"))
    state.apply(
        StreamReceived(
            BookStreamEvent(StreamKind.BOOK, rejected_book),
            1.0,
        )
    )
    item = BookStreamEvent(StreamKind.BOOK, rejected_book)
    state.apply(
        DispatchCompleted(
            item,
            DispatchOutcome.skipped(DispatchSkipReason.BOOK_CROSSED),
            2.0,
        )
    )

    assert state.stream_counts[StreamKind.BOOK] == 1
    assert state.books == {}
    assert tuple(state.chart_tokens) == ()


def test_dashboard_promotes_accepted_books_for_valuation() -> None:
    state = DashboardState(require_accepted_books=True)
    book = _book("accepted", Decimal("0.40"), Decimal("0.60"), received_at_ms=1_000)
    item = BookStreamEvent(StreamKind.BOOK, book)
    state.apply(StreamReceived(item, 1.0))
    state.apply(DispatchCompleted(item, DispatchOutcome.accepted_event(), 2.0))
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("accepted", Decimal("1"), Decimal("0.50")),),
    )

    assert state.pending_books == {}
    assert tuple(state.chart_tokens) == ("accepted",)
    assert state.executable_equity(now_ms=1_000) == Decimal("90.40")


def test_dashboard_recovers_held_position_mark_from_subscription_bootstrap() -> None:
    book = _book("held", Decimal("0.40"), Decimal("0.60"), received_at_ms=1_000)

    state = DashboardState(require_accepted_books=True, initial_cash_usdc=Decimal("100"))
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("held", Decimal("1"), Decimal("0.50")),),
    )
    assert state.executable_equity(now_ms=1_000) is None

    state.apply(PortfolioBookBootstrap(book, 1.0))

    assert state.executable_equity(now_ms=1_000) == Decimal("90.40")


def test_position_book_bootstrap_is_dashboard_only_and_rejects_crossed_books() -> None:
    valid_book = _book("held", Decimal("0.40"), Decimal("0.60"))
    crossed_book = _book("crossed", Decimal("0.70"), Decimal("0.60"))

    class Paper:
        class Portfolio:
            positions = {"held": object(), "crossed": object()}

        portfolio = Portfolio()

    class Clob:
        async def latest(self, token_id: str) -> BookSnapshot:
            return {"held": valid_book, "crossed": crossed_book}[token_id]

    async def run() -> list[object]:
        observer = RecordingObserver()
        await emit_paper_position_book_bootstraps(Paper(), Clob(), observer)
        return observer.events

    events = asyncio.run(run())

    assert len(events) == 1
    assert isinstance(events[0], PortfolioBookBootstrap)
    assert events[0].book == valid_book


def test_dashboard_marks_expired_books_unavailable() -> None:
    state = DashboardState(book_max_age_ms=100)
    state.books["token"] = _book("token", Decimal("0.40"), Decimal("0.60"), received_at_ms=1_000)
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("token", Decimal("1"), Decimal("0.50")),),
    )

    assert state.executable_equity(now_ms=1_100) == Decimal("90.40")
    assert state.executable_equity(now_ms=1_101) is None


def test_dashboard_tracks_dispatch_skips_and_rejected_fills() -> None:
    state = DashboardState()
    rejected_fill = FillEvent(
        order_id="order",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.REJECTED,
        requested_size=Decimal("1"),
        filled_size=Decimal("0"),
        average_price=None,
        fee_usdc=Decimal("0"),
        received_at_ms=1,
        reject_reason=FillRejectReason.BOOK_CROSSED,
        reject_message="crossed book",
    )
    state.apply(
        DispatchCompleted(
            BookStreamEvent(StreamKind.BOOK, _book("token", Decimal("0.4"), Decimal("0.6"))),
            DispatchOutcome.skipped(DispatchSkipReason.BOOK_CROSSED),
            1.0,
        )
    )
    state.apply(FillCompleted(OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("1")), rejected_fill, None, 3, 2.0))

    assert state.skipped_dispatches == 1
    assert state.rejected_count == 1
    assert state.pending_trade_markers == {}


def test_dashboard_samples_buy_fills_as_trade_markers() -> None:
    state = DashboardState()
    fill = FillEvent(
        order_id="order",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.PARTIAL,
        requested_size=Decimal("2"),
        filled_size=Decimal("1"),
        average_price=Decimal("0.47"),
        fee_usdc=Decimal("0"),
        received_at_ms=1,
    )

    state.apply(
        FillCompleted(
            OrderRequest("token", Side.BUY, Decimal("0.5"), Decimal("2")),
            fill,
            None,
            3,
            2.0,
        )
    )
    state.record_chart_sample(now_ms=1_000)

    assert tuple(state.chart_tokens) == ("token",)
    assert list(state.trade_marker_history["token"]) == [(Side.BUY,)]
    assert state.pending_trade_markers == {}


def test_dashboard_samples_sell_fills_as_trade_markers() -> None:
    state = DashboardState()
    fill = FillEvent(
        order_id="order",
        token_id="token",
        side=Side.SELL,
        status=OrderStatus.FILLED,
        requested_size=Decimal("1"),
        filled_size=Decimal("1"),
        average_price=Decimal("0.53"),
        fee_usdc=Decimal("0"),
        received_at_ms=1,
    )

    state.apply(
        FillCompleted(
            OrderRequest("token", Side.SELL, Decimal("0.5"), Decimal("1")),
            fill,
            None,
            3,
            2.0,
        )
    )
    state.record_chart_sample(now_ms=1_000)

    assert list(state.trade_marker_history["token"]) == [(Side.SELL,)]


def test_dashboard_render_handles_all_missing_chart_samples() -> None:
    state = DashboardState(chart_tokens=deque(("one", "two")))
    state.price_history = {
        "one": deque((nan,)),
        "two": deque((nan,)),
    }
    state.wallet_value_history.append(nan)

    Console(width=120, height=35).print(render_dashboard(state, 120, 35))


def test_dashboard_chart_bounds_fix_prices_and_pad_wallet_value(monkeypatch) -> None:
    state = DashboardState(chart_tokens=deque(("token",)))
    state.price_history = {"token": deque((0.45, 0.55))}
    state.wallet_value_history = deque((100.0, 110.0))
    configurations: list[dict[str, object]] = []

    def plot(series, config):
        configurations.append(config)
        return "chart"

    monkeypatch.setattr("polybot.cli.dashboard.render.asciichartpy.plot", plot)

    render_dashboard(state, 120, 35)

    price_config, wallet_config = configurations
    assert price_config["min"] == PRICE_CHART_MIN
    assert price_config["max"] == PRICE_CHART_MAX
    assert wallet_config["min"] < 100.0
    assert wallet_config["max"] > 110.0


def test_dashboard_wallet_chart_padding_follows_observed_variance(monkeypatch) -> None:
    state = DashboardState(chart_tokens=deque(("token",)))
    state.price_history = {"token": deque((0.45, 0.55))}
    state.wallet_value_history = deque((100.0, 100.1))
    configurations: list[dict[str, object]] = []

    def plot(series, config):
        configurations.append(config)
        return "chart"

    monkeypatch.setattr("polybot.cli.dashboard.render.asciichartpy.plot", plot)

    render_dashboard(state, 120, 35)

    wallet_config = configurations[1]
    assert wallet_config["min"] == pytest.approx(99.985)
    assert wallet_config["max"] == pytest.approx(100.115)


def test_dashboard_price_chart_is_taller_on_normal_terminal_heights() -> None:
    assert _price_chart_height(120, 35) == 18
    assert _price_chart_height(120, 100) == 18
    assert _price_chart_height(80, 35) == 9


def test_dashboard_time_zoom_retains_history_and_changes_window() -> None:
    state = DashboardState()
    for value in range(MAX_CHART_HISTORY_POINTS + 1):
        state.wallet_value_history.append(float(value))
    state.record_chart_sample()

    assert len(state.wallet_value_history) == MAX_CHART_HISTORY_POINTS
    assert state.chart_window_points(100) == 88
    assert state.zoom_time(-1)
    assert state.chart_window_points(100) == 44
    assert state.zoom_time(1)
    assert state.reset_time_zoom() is False


def test_dashboard_time_zoom_keeps_the_rendered_chart_width(monkeypatch) -> None:
    state = DashboardState(chart_tokens=deque(("token",)))
    state.price_history = {"token": deque(float(value) / 200 for value in range(200))}
    state.price_stale_history = {"token": deque(False for _ in range(200))}
    state.wallet_value_history = deque(float(value) for value in range(200))
    state.wallet_value_stale_history = deque(False for _ in range(200))
    state.chart_sample_times = deque(float(value) for value in range(200))
    rendered_widths: list[int] = []

    def plot(series, config):
        rendered_widths.append(len(series[0]))
        return "chart"

    monkeypatch.setattr("polybot.cli.dashboard.render.asciichartpy.plot", plot)

    render_dashboard(state, 120, 35)
    state.zoom_time(-1)
    render_dashboard(state, 120, 35)
    state.zoom_time(2)
    render_dashboard(state, 120, 35)

    assert rendered_widths == [68, 68, 68, 68, 68, 68]


def test_dashboard_shows_visible_time_range_endpoints() -> None:
    state = DashboardState()
    state.chart_sample_times = deque((1_700_000_000.0, 1_700_000_010.0))

    label = _chart_time_range(state, 100).plain

    assert datetime.fromtimestamp(1_700_000_000).strftime("%H:%M:%S") in label
    assert datetime.fromtimestamp(1_700_000_010).strftime("%H:%M:%S") in label


def test_dashboard_keyboard_time_zoom_controls_change_only_chart_window() -> None:
    dashboard = TerminalDashboard(Console(width=80, height=24))

    dashboard._handle_key("z")
    assert dashboard._state.time_zoom_level == -1
    dashboard._handle_key("x")
    assert dashboard._state.time_zoom_level == 0
    dashboard._handle_key("r")
    assert dashboard._state.time_zoom_level == 0


def test_dashboard_keyboard_switches_views_and_pages_wallets() -> None:
    dashboard = TerminalDashboard(Console(width=80, height=24))
    dashboard._state.set_wallet_lanes(tuple(f"0x{index:040x}" for index in range(20)))

    dashboard._handle_key("v")
    assert dashboard._state.view is DashboardView.WALLET
    dashboard._handle_key("j")
    assert dashboard._state.wallet_page == 1
    dashboard._handle_key("k")
    assert dashboard._state.wallet_page == 0
    dashboard._handle_key("v")
    assert dashboard._state.view is DashboardView.MARKET


def test_dashboard_projects_wallet_trades_and_dispatch_status_by_wallet_source() -> None:
    state = DashboardState()
    first = _wallet_trade("0x" + "1" * 40, "same", Side.BUY, 1_000)
    second = _wallet_trade("0x" + "2" * 40, "same", Side.SELL, 1_001)
    first_item = WalletStreamEvent(StreamKind.WALLET, first)
    second_item = WalletStreamEvent(StreamKind.WALLET, second)
    state.apply(StreamReceived(first_item, 1.0))
    state.apply(StreamReceived(second_item, 1.0))
    state.apply(
        DispatchCompleted(
            first_item,
            DispatchOutcome.skipped(DispatchSkipReason.DUPLICATE_SOURCE_EVENT),
            2.0,
        )
    )
    state.apply(DispatchCompleted(second_item, DispatchOutcome.accepted_event(), 2.0))

    assert tuple(state.wallet_lanes) == (first.wallet, second.wallet)
    assert [event.accepted for event in state.wallet_timeline] == [False, True]
    assert [event.notional for event in state.wallet_timeline] == [Decimal("1"), Decimal("1")]


def test_wallet_timeline_buckets_by_trade_time_and_styles_skipped_events() -> None:
    state = DashboardState()
    skipped = _wallet_trade("0x" + "3" * 40, "skipped", Side.BUY, 1_000)
    accepted = _wallet_trade("0x" + "4" * 40, "accepted", Side.SELL, 1_500)
    skipped_item = WalletStreamEvent(StreamKind.WALLET, skipped)
    accepted_item = WalletStreamEvent(StreamKind.WALLET, accepted)
    state.apply(StreamReceived(skipped_item, 1.0))
    state.apply(StreamReceived(accepted_item, 1.0))
    state.apply(
        DispatchCompleted(
            skipped_item,
            DispatchOutcome.skipped(DispatchSkipReason.WALLET_NOT_TRACKED),
            1.0,
        )
    )
    state.apply(DispatchCompleted(accepted_item, DispatchOutcome.accepted_event(), 1.0))

    buckets = _wallet_timeline_buckets(
        state.wallet_timeline,
        list(state.wallet_lanes),
        1.0,
        2.0,
        10,
    )
    skipped_glyph, skipped_style = _wallet_bucket_glyph(buckets[skipped.wallet][0], Decimal("1"))
    accepted_glyph, accepted_style = _wallet_bucket_glyph(buckets[accepted.wallet][5], Decimal("1"))

    assert skipped_glyph == "◆"
    assert skipped_style == "dim green"
    assert accepted_glyph == "◆"
    assert accepted_style == "bold red"


def test_dashboard_renders_wallet_view_with_trade_time_lanes() -> None:
    state = DashboardState(view=DashboardView.WALLET)
    trade = _wallet_trade("0x" + "5" * 40, "trade", Side.BUY, 1_000)
    state.apply(StreamReceived(WalletStreamEvent(StreamKind.WALLET, trade), 1.0))
    state.record_chart_sample(now_ms=1_000)
    output = StringIO()

    Console(file=output, width=120, height=35).print(render_dashboard(state, 120, 35))

    assert "Followed wallet activity" in output.getvalue()
    assert "0x5555" in output.getvalue()


def test_dashboard_samples_executable_wallet_value() -> None:
    state = DashboardState(initial_cash_usdc=Decimal("100"))
    state.portfolio = PortfolioSnapshot(Decimal("125"), Decimal("0"), ())

    state.record_chart_sample()

    assert list(state.wallet_value_history) == [125.0]


def test_dashboard_retains_stale_chart_values_with_stale_markers() -> None:
    state = DashboardState(book_max_age_ms=100)
    state.apply(
        StreamReceived(
            BookStreamEvent(
                StreamKind.BOOK,
                _book("token", Decimal("0.4"), Decimal("0.6"), received_at_ms=1_000),
            ),
            1.0,
        )
    )
    state.portfolio = PortfolioSnapshot(
        Decimal("90"),
        Decimal("0"),
        (PortfolioPositionSnapshot("token", Decimal("1"), Decimal("0.5")),),
    )

    state.record_chart_sample(now_ms=1_000)
    state.record_chart_sample(now_ms=1_101)

    assert list(state.price_history["token"]) == [0.5, 0.5]
    assert list(state.price_stale_history["token"]) == [False, True]
    assert list(state.wallet_value_history) == [90.4, 90.4]
    assert list(state.wallet_value_stale_history) == [False, True]


def test_dashboard_removes_settled_market_state_and_counts_it_once() -> None:
    state = DashboardState()
    settled_yes = _book("settled-yes", Decimal("0.4"), Decimal("0.6"))
    settled_no = _book("settled-no", Decimal("0.3"), Decimal("0.7"))
    active = _book("active", Decimal("0.45"), Decimal("0.55"))
    for book in (settled_yes, settled_no, active):
        state.apply(StreamReceived(BookStreamEvent(StreamKind.BOOK, book), 1.0))
    state.record_chart_sample(now_ms=1_000)
    state.pending_books[settled_yes.token_id] = settled_yes
    state.pending_trade_markers[settled_no.token_id] = [Side.BUY]
    resolution = MarketResolutionEvent(
        condition_id="settled-condition",
        market_slug="settled-market",
        token_ids=(settled_yes.token_id, settled_no.token_id),
        winning_token_id=settled_yes.token_id,
        winning_outcome=YES_OUTCOME,
        resolved_at_ms=1_000,
        source="test",
    )
    settlement = MarketSettlementEvent(
        resolution=resolution,
        paper_positions=(),
        followed_wallet_positions=(),
        settled_at_ms=1_001,
    )
    event = MarketSettled(
        settlement,
        PortfolioSnapshot(Decimal("100"), Decimal("0"), ()),
        2.0,
    )

    state.apply(event)
    state.apply(event)

    assert tuple(state.chart_tokens) == (active.token_id,)
    assert settled_yes.token_id not in state.books
    assert settled_no.token_id not in state.pending_books
    assert settled_yes.token_id not in state.price_history
    assert settled_no.token_id not in state.pending_trade_markers
    assert active.token_id in state.price_history
    assert state.resolved_market_count == 1
    output = StringIO()
    Console(file=output, width=120, height=35).print(render_dashboard(state, 120, 35))
    assert "resolved 1" in output.getvalue()
    assert "SETTLED settled-market" not in output.getvalue()


def test_dashboard_renders_stale_samples_in_dimmed_series(monkeypatch) -> None:
    state = DashboardState(chart_tokens=deque(("token",)))
    state.price_history = {"token": deque((0.45, 0.55))}
    state.price_stale_history = {"token": deque((False, True))}
    state.wallet_value_history = deque((100.0, 110.0))
    state.wallet_value_stale_history = deque((False, True))
    calls: list[tuple[object, dict[str, object]]] = []

    def plot(series, config):
        calls.append((series, config))
        return "chart"

    monkeypatch.setattr("polybot.cli.dashboard.render.asciichartpy.plot", plot)

    render_dashboard(state, 120, 35)

    price_series, price_config = calls[0]
    wallet_series, wallet_config = calls[1]
    assert price_series[0][0] == 0.45
    assert isnan(price_series[0][-1])
    assert isnan(price_series[1][0])
    assert price_series[1][-1] == 0.55
    assert len(price_config["colors"]) == 2
    assert wallet_series[0][0] == 100.0
    assert isnan(wallet_series[0][-1])
    assert isnan(wallet_series[1][0])
    assert wallet_series[1][-1] == 110.0
    assert len(wallet_config["colors"]) == 2


def test_dashboard_renders_trade_markers_on_token_lines_with_side_colors() -> None:
    state = DashboardState(chart_tokens=deque(("one", "two")))
    state.price_history = {
        "one": deque((0.4, 0.5, 0.6)),
        "two": deque((0.6, 0.5, 0.4)),
    }
    state.price_stale_history = {
        "one": deque((False, False, False)),
        "two": deque((False, False, False)),
    }
    state.trade_marker_history = {
        "one": deque(((), (Side.BUY,), ())),
        "two": deque(((Side.SELL,), (), (Side.BUY, Side.SELL))),
    }
    state.chart_sample_times = deque((1.0, 2.0, 3.0))

    series, colors = _price_chart_series(state, 80)

    assert len(series) == 8
    assert colors[2] == asciichartpy.lightgreen
    assert colors[5] == asciichartpy.red
    assert colors[6] == asciichartpy.lightgreen
    assert colors[7] == asciichartpy.red
    for marker_index, token_series_index in ((2, 0), (5, 3), (6, 3), (7, 3)):
        display_index = next(
            index
            for index, value in enumerate(series[marker_index])
            if not isnan(value)
        )
        assert series[marker_index][display_index] == series[token_series_index][display_index]


def test_dashboard_ticker_removes_terminal_control_characters() -> None:
    state = DashboardState()
    state.apply(RuntimeFailed("bad\x1b[31m\nmessage", 1.0))

    assert "\x1b" not in state.ticker[0].message
    assert "\n" not in state.ticker[0].message


def test_dashboard_aggregates_consecutive_identical_ticker_events() -> None:
    state = DashboardState()
    state.apply(RuntimeFailed("repeated failure", 1.0))
    state.apply(RuntimeFailed("repeated failure", 2.0))
    state.apply(RuntimeFailed("another failure", 3.0))
    state.apply(RuntimeFailed("repeated failure", 4.0))

    assert [(row.message, row.count) for row in state.ticker] == [
        ("RUN FAILED repeated failure", 1),
        ("RUN FAILED another failure", 1),
        ("RUN FAILED repeated failure", 2),
    ]
    output = StringIO()
    Console(file=output, width=80, height=24).print(render_dashboard(state, 80, 24))

    assert "RUN FAILED repeated failure x2" in output.getvalue()


@pytest.mark.parametrize("values", ((inf,), (-inf,), (inf, -inf)))
def test_chart_bounds_ignore_infinite_values(values: tuple[float, ...]) -> None:
    assert padded_value_bounds(values) == (None, None)


def test_charting_sanitizes_infinite_samples_before_rendering(monkeypatch) -> None:
    captured: list[list[float]] = []

    def capture_plot(series, config):
        captured.append(series)
        return "chart"

    monkeypatch.setattr(asciichartpy, "plot", capture_plot)

    chart = render_chart([[0.2, inf, 0.8]], ("green",), 4, "empty")

    assert chart.plain == "chart"
    assert captured[0][0] == 0.2
    assert isnan(captured[0][1])
    assert captured[0][2] == 0.8
    assert padded_value_bounds((0.2, inf, 0.8)) == pytest.approx((0.11, 0.89))


def test_resample_indices_validates_before_using_the_pure_formula() -> None:
    assert resample_indices(0, 3) == []
    assert resample_indices(3, 1) == [2]
    with pytest.raises(ValueError, match="nonnegative"):
        resample_indices(-1, 3)
    with pytest.raises(ValueError, match="positive"):
        resample_indices(3, 0)


def _book(
    token_id: str,
    bid: Decimal,
    ask: Decimal,
    received_at_ms: int = 1,
) -> BookSnapshot:
    return BookSnapshot(
        token_id=token_id,
        bids=(BookLevel(bid, Decimal("1")),),
        asks=(BookLevel(ask, Decimal("1")),),
        received_at_ms=received_at_ms,
    )


def _wallet_trade(wallet: str, source_id: str, side: Side, timestamp_ms: int) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet=wallet,
        condition_id="condition",
        token_id="token",
        side=side,
        size=Decimal("2"),
        price=Decimal("0.5"),
        source_id=source_id,
        trade_timestamp_ms=timestamp_ms,
        observed_at_ms=timestamp_ms + 10,
        market_slug="market",
        outcome=YES_OUTCOME,
    )
