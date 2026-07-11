import asyncio
from threading import Event
from collections import deque
from decimal import Decimal
from math import nan

import pytest
from rich.console import Console

from bots.cli.dashboard.render import render_dashboard
from bots.cli.dashboard.controller import TerminalDashboard
from bots.cli.dashboard.state import MAX_CHART_TOKENS, DashboardState
from bots.cli.observability.broker import ObservableBroker
from bots.cli.observability.events import (
    BrokerFailed,
    DispatchCompleted,
    FillCompleted,
    OrderSubmitted,
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
    RuntimeStarted,
    RuntimeFailed,
    StreamReceived,
)
from bots.cli.observability.observer import (
    RuntimeObserver,
    emit_observer,
    start_observer,
    stop_observer,
)
from bots.cli.streams import BookStreamEvent, StreamKind, WalletStreamEvent
from bots.framework.config import BotConfig
from bots.framework.events import FillEvent, FillRejectReason, OrderRequest, OrderStatus, Side
from bots.framework.events.books import BookLevel, BookSnapshot
from bots.framework.events.wallet_trades import WalletTradeEvent


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

    monkeypatch.setattr("bots.cli.dashboard.controller.Live", BlockingLive)

    async def run() -> bool:
        dashboard = TerminalDashboard(Console(width=80, height=24))
        start_task = asyncio.create_task(dashboard.start(BotConfig(name="dashboard")))
        await asyncio.to_thread(started.wait, 1)
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

    monkeypatch.setattr("bots.cli.dashboard.controller.Live", BlockingLive)

    async def run() -> bool:
        dashboard = TerminalDashboard(Console(width=80, height=24))
        await dashboard.start(BotConfig(name="dashboard"))
        dashboard.emit(RuntimeStarted.from_config(BotConfig(name="dashboard")))
        await asyncio.to_thread(update_started.wait, 1)
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


def test_dashboard_tracks_market_wallet_and_chart_events() -> None:
    state = DashboardState()
    for index in range(MAX_CHART_TOKENS + 1):
        token_id = f"token-{index}"
        state.apply(
            StreamReceived(
                BookStreamEvent(StreamKind.BOOK, _book(token_id, Decimal("0.4"), Decimal("0.6"))),
                float(index),
            )
        )
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
    state.sample(80)

    expected_tokens = tuple(
        f"token-{index}"
        for index in range(1, MAX_CHART_TOKENS + 1)
    )
    assert tuple(state.chart_tokens) == expected_tokens
    assert state.average_wallet_lag_ms() == 125
    assert state.stream_counts[StreamKind.BOOK] == 5
    assert state.stream_counts[StreamKind.WALLET] == 1
    assert all(len(values) == 1 for values in state.price_history.values())


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
    from bots.framework.dispatch import DispatchOutcome, DispatchSkipReason

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
    from bots.framework.dispatch import DispatchOutcome

    state.apply(DispatchCompleted(item, DispatchOutcome.accepted_event(), 2.0))
    state.portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("90"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(PortfolioPositionSnapshot("accepted", Decimal("1"), Decimal("0.50")),),
    )

    assert state.pending_books == {}
    assert tuple(state.chart_tokens) == ("accepted",)
    assert state.executable_equity(now_ms=1_000) == Decimal("90.40")


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
    from bots.framework.dispatch import DispatchOutcome, DispatchSkipReason

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


def test_dashboard_render_handles_all_missing_chart_samples() -> None:
    state = DashboardState(chart_tokens=deque(("one", "two")))
    state.price_history = {
        "one": deque((nan,)),
        "two": deque((nan,)),
    }
    state.pnl_history.append(nan)

    Console(width=120, height=35).print(render_dashboard(state, 120, 35))


def test_dashboard_ticker_removes_terminal_control_characters() -> None:
    state = DashboardState()
    state.apply(RuntimeFailed("bad\x1b[31m\nmessage", 1.0))

    assert "\x1b" not in state.ticker[0].message
    assert "\n" not in state.ticker[0].message


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
