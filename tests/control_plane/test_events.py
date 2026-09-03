import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

import polybot_control_plane.events.writer as event_writer_module
from polybot_control_plane.events.ids import MAX_DURABLE_EVENT_ID
from polybot_control_plane.events.store import EventStore
from polybot.cli.observability.events import (
    BootstrapProgress,
    BrokerFailed,
    DispatchCompleted,
    FillCompleted,
    MarketSettled,
    OrderSubmitted,
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeStateChanged,
    StreamReceived,
    StreamHealth,
)
from polybot.cli.observability.states import BootstrapPhase, RuntimeState
from polybot.cli.streams.contracts import ResolutionStreamEvent, WalletStreamEvent
from polybot.cli.streams.contracts import (
    BookGapStreamEvent,
    BookStreamEvent,
)
from polybot.cli.dashboard.state import DashboardState
from polybot.dashboard.projection import DashboardProjection
from polybot.dashboard.contracts import (
    CHART_SAMPLE_INTERVAL_SECONDS,
    DashboardSample,
    EquityChartPoint,
    MarketChartPoint,
    WalletChartPoint,
)
from polybot.cli.streams.kinds import StreamKind
from polybot.framework.activity import ActivitySeverity, BotActivityEvent
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from polybot.framework.events.books import (
    BookGapEvent,
    BookGapReason,
    BookLevel,
    BookSnapshot,
)
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
    SettledPosition,
)
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot_control_plane.events.channels import run_event_channel
from polybot_control_plane.events.contracts import (
    DURABLE_EVENT_ADAPTER,
    BrokerOrderPayload,
    DurableEvent,
    DurableEventBase,
    RunLifecycleEvent,
    RunStatusPayload,
    PortfolioSnapshotPayload,
    WalletTimelineDurableEvent,
    WalletTimelinePayload,
)
from polybot_control_plane.events.kinds import (
    EVENT_DISCRIMINATOR_FIELD,
    EventKind,
    LiveEventKind,
)
from polybot_control_plane.events.contracts.payloads import (
    EquityChartPointPayload,
    MarketChartPointPayload,
)
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.events.projection import (
    project_live_chart_events,
    project_live_stream_health,
    project_runtime_event_to_durable,
)
from polybot_control_plane.events.writer import RunEventWriter
from polybot_control_plane.runs.status import RunStatus


def test_runtime_projection_keeps_typed_lifecycle_payloads() -> None:
    run_id = uuid4()
    started, = project_runtime_event_to_durable(
        run_id,
        RuntimeStarted("run", BotMode.PAPER, Decimal("100"), 12.0),
    )
    running, = project_runtime_event_to_durable(
        run_id,
        RuntimeStateChanged(RuntimeState.RUNNING, 12.5),
    )

    assert started.kind is EventKind.RUN_LIFECYCLE
    assert started.payload.initial_cash_usdc == Decimal("100")
    assert running.run_id == run_id
    assert running.payload.status is RunStatus.RUNNING
    assert running.occurred_at.tzinfo is UTC
    assert project_runtime_event_to_durable(
        run_id,
        RuntimeStateChanged(RuntimeState.STOPPED, 13.0),
    ) == ()


def test_runtime_projection_maps_every_immediately_durable_event_kind() -> None:
    run_id = uuid4()
    order = _order()
    events = (
        BootstrapProgress(BootstrapPhase.MARKETS, 1, 2, 1.0),
        BotActivityEvent("ready", ActivitySeverity.SUCCESS, 1.0),
        OrderSubmitted(order, 1.0),
        BrokerFailed(order, "rejected", 1.0),
        RuntimeFailed("safe", 1.0),
        DispatchCompleted(
            WalletStreamEvent(kind=StreamKind.WALLET, event=_wallet_trade()),
            DispatchOutcome.accepted_event(),
            1.0,
        ),
    )

    projected = tuple(
        project_runtime_event_to_durable(run_id, event)[0] for event in events
    )

    assert tuple(event.kind for event in projected) == (
        EventKind.RUN_BOOTSTRAP,
        EventKind.BOT_ACTIVITY,
        EventKind.BROKER_ORDER,
        EventKind.BROKER_FAILURE,
        EventKind.RUN_FAILURE,
        EventKind.WALLET_TIMELINE,
    )
    wallet_point = projected[-1].payload.point
    assert wallet_point.source_key == _wallet_trade().source_key
    assert wallet_point.notional == Decimal("0.5")
    assert wallet_point.market_label == "token"
    assert wallet_point.accepted is True
    skipped, = project_runtime_event_to_durable(
        run_id,
        DispatchCompleted(
            WalletStreamEvent(kind=StreamKind.WALLET, event=_wallet_trade()),
            DispatchOutcome.skipped(DispatchSkipReason.WALLET_NOT_TRACKED),
            1.0,
        ),
    )
    assert skipped.payload.point.accepted is False
    assert project_runtime_event_to_durable(
        run_id,
        StreamHealth(1, 2, 3, False, 1.0, 4, 1),
    ) == ()


def test_live_dashboard_projection_preserves_sample_and_wallet_fields() -> None:
    run_id = uuid4()
    occurred_at = datetime(2026, 8, 23, tzinfo=UTC)
    sample = DashboardSample(
        sampled_at_ms=42,
        markets=(
            MarketChartPoint(
                token_id="token",
                label="Market · Up",
                value=Decimal("0.55"),
                status=ValuationStatus.STALE,
                markers=(Side.BUY,),
            ),
        ),
        equity=EquityChartPoint(
            value=None,
            status=ValuationStatus.UNAVAILABLE,
        ),
    )
    wallet_point = WalletChartPoint(
        source_key="wallet\0source",
        wallet="wallet",
        trade_timestamp_ms=41,
        side=Side.SELL,
        notional=Decimal("1.25"),
        market_label="Market · Down",
        accepted=False,
    )

    market, equity, wallet = project_live_chart_events(
        run_id,
        sample,
        (wallet_point,),
        occurred_at=occurred_at,
    )

    assert market.payload.model_dump() == {
        "sampled_at_ms": 42,
        "points": ({
            "token_id": "token",
            "label": "Market · Up",
            "value": Decimal("0.55"),
            "status": ValuationStatus.STALE,
            "markers": (Side.BUY,),
        },),
    }
    assert equity.payload.model_dump() == {
        "sampled_at_ms": 42,
        "point": {
            "value": None,
            "status": ValuationStatus.UNAVAILABLE,
        },
    }
    assert wallet.payload.model_dump() == {
        "sampled_at_ms": 42,
        "points": ({
            "source_key": "wallet\0source",
            "wallet": "wallet",
            "trade_timestamp_ms": 41,
            "side": Side.SELL,
            "notional": Decimal("1.25"),
            "market_label": "Market · Down",
            "accepted": False,
        },),
    }
    health = project_live_stream_health(
        run_id,
        StreamHealth(1, 2, 3, True, 1.0, 4, 1),
        occurred_at=occurred_at,
    )
    assert health.payload.model_dump() == {
        "queue_depth": 1,
        "peak_queue_depth": 2,
        "book_dispatch_lag_ms": 3,
        "book_stale": True,
        "book_received_count": 4,
        "book_coalesced_count": 1,
    }


def test_durable_event_adapter_rejects_invalid_finite_state() -> None:
    event, = project_runtime_event_to_durable(
        uuid4(),
        RuntimeStateChanged(RuntimeState.RUNNING, 1.0),
    )
    invalid = event.model_dump(mode="json")
    status_field, = RunStatusPayload.model_fields
    invalid["payload"][status_field] = "bogus"

    with pytest.raises(ValidationError):
        DURABLE_EVENT_ADAPTER.validate_python(invalid)


def test_fill_and_settlement_project_portfolio_snapshots() -> None:
    run_id = uuid4()
    order = _order()
    portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("99.5"),
        cumulative_fees_usdc=Decimal("0.01"),
        positions=(
            PortfolioPositionSnapshot("token", Decimal("1"), Decimal("0.5")),
        ),
    )
    fill = FillEvent(
        order_id="order",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("1"),
        filled_size=Decimal("1"),
        average_price=Decimal("0.5"),
        fee_usdc=Decimal("0.01"),
        received_at_ms=1,
    )
    resolution = MarketResolutionEvent(
        condition_id="condition",
        market_slug="market",
        token_ids=("token", "other"),
        winning_token_id="token",
        winning_outcome="Up",
        resolved_at_ms=1,
        source="test",
    )
    settlement = MarketSettlementEvent(
        resolution=resolution,
        paper_positions=(
            SettledPosition(
                owner="paper",
                token_id="token",
                size=Decimal("1"),
                payout_per_token=Decimal("1"),
                cash_payout_usdc=Decimal("1"),
            ),
        ),
        followed_wallet_positions=(),
        settled_at_ms=1,
    )

    fill_events = project_runtime_event_to_durable(
        run_id,
        FillCompleted(order, fill, portfolio, 1, 1.0),
    )
    settlement_events = project_runtime_event_to_durable(
        run_id,
        MarketSettled(settlement, portfolio, 1.0),
    )

    assert tuple(event.kind for event in fill_events) == (
        EventKind.BROKER_FILL,
        EventKind.PORTFOLIO_SNAPSHOT,
    )
    assert tuple(event.kind for event in settlement_events) == (
        EventKind.MARKET_SETTLEMENT,
        EventKind.PORTFOLIO_SNAPSHOT,
    )
    fill_without_portfolio = project_runtime_event_to_durable(
        run_id,
        FillCompleted(order, fill, None, 1, 1.0),
    )
    assert tuple(event.kind for event in fill_without_portfolio) == (
        EventKind.BROKER_FILL,
    )
    assert project_runtime_event_to_durable(
        run_id,
        DispatchCompleted(
            ResolutionStreamEvent(StreamKind.RESOLUTION, resolution),
            DispatchOutcome.accepted_event(),
            1.0,
        ),
    ) == ()
    assert project_runtime_event_to_durable(
        run_id,
        StreamReceived(
            ResolutionStreamEvent(StreamKind.RESOLUTION, resolution),
            1.0,
        ),
    ) == ()


def test_durable_event_adapter_rejects_invalid_wallet_trade() -> None:
    event, = project_runtime_event_to_durable(
        uuid4(),
        DispatchCompleted(
            WalletStreamEvent(kind=StreamKind.WALLET, event=_wallet_trade()),
            DispatchOutcome.accepted_event(),
            1.0,
        ),
    )
    invalid = event.model_dump(mode="json")
    payload_field = next(
        field
        for field in WalletTimelineDurableEvent.model_fields
        if field not in DurableEventBase.model_fields
        and field != EVENT_DISCRIMINATOR_FIELD
    )
    trade_field = next(iter(WalletTimelinePayload.model_fields))
    invalid[payload_field][trade_field] = asdict(
        replace(_wallet_trade(), size=Decimal("-1"))
    )

    with pytest.raises(ValidationError, match="wallet timeline trade is invalid"):
        DURABLE_EVENT_ADAPTER.validate_python(invalid)

    mismatched = event.model_dump(mode="json")
    mismatched["payload"]["point"]["notional"] = "999"
    with pytest.raises(ValidationError, match="point does not match"):
        DURABLE_EVENT_ADAPTER.validate_python(mismatched)


def test_durable_payloads_reject_invalid_orders_and_portfolio_positions() -> None:
    with pytest.raises(ValidationError, match="missing token_id"):
        BrokerOrderPayload(order=replace(_order(), token_id=""))
    with pytest.raises(ValidationError, match="token IDs"):
        PortfolioSnapshotPayload(
            cash_usdc=Decimal("1"),
            cumulative_fees_usdc=Decimal("0"),
            positions=(
                PortfolioPositionSnapshot("", Decimal("1"), Decimal("0.5")),
            ),
        )


def test_chart_payloads_reject_inconsistent_values() -> None:
    with pytest.raises(ValidationError, match="unavailable chart value must be null"):
        MarketChartPointPayload(
            token_id="token",
            label="Market",
            value=Decimal("0.5"),
            status="unavailable",
            markers=(),
        )
    with pytest.raises(ValidationError, match="finite"):
        EquityChartPointPayload(
            value=Decimal("NaN"),
            status=ValuationStatus.FRESH,
        )
    with pytest.raises(ValidationError, match="valid average outcome price"):
        PortfolioSnapshotPayload(
            cash_usdc=Decimal("1"),
            cumulative_fees_usdc=Decimal("0"),
            positions=(
                PortfolioPositionSnapshot("token", Decimal("1"), Decimal("2")),
            ),
        )


def test_terminal_lifecycle_factory_rejects_nonterminal_status() -> None:
    with pytest.raises(ValueError, match="terminal status"):
        RunLifecycleEvent.from_terminal_status(
            uuid4(),
            RunStatus.RUNNING,
            occurred_at=datetime.now(UTC),
        )


def test_observer_drains_accepted_events_and_isolates_writer_failures() -> None:
    async def scenario() -> tuple[list[EventKind], list[EventKind]]:
        collecting = _CollectingWriter()
        observer = WebRuntimeObserver(uuid4(), collecting)
        observer.emit(RuntimeFailed("before-start", 1.0))
        await observer.start(BotConfig(name="test"))
        observer.emit(RuntimeFailed("first", 2.0))
        observer.emit(RuntimeFailed("second", 3.0))
        await observer.stop()

        failing = _CollectingWriter(fail=True)
        failing_observer = WebRuntimeObserver(uuid4(), failing)
        await failing_observer.start(BotConfig(name="test"))
        failing_observer.emit(RuntimeFailed("ignored failure", 4.0))
        failing_observer.emit(StreamHealth(1, 2, 3, False, 5.0, 4, 1))
        await failing_observer.stop()
        return (
            [event.kind for event in collecting.events],
            [event.kind for event in failing.events],
        )

    collected, failed = asyncio.run(scenario())

    assert collected == [
        EventKind.RUN_FAILURE,
        EventKind.RUN_FAILURE,
        EventKind.CHART_SAMPLE,
    ]
    assert failed == [
        EventKind.RUN_FAILURE,
        EventKind.CHART_SAMPLE,
        EventKind.STREAM_HEALTH,
    ]


def test_observer_persists_only_latest_stream_health_during_shutdown() -> None:
    async def scenario() -> list[DurableEvent]:
        writer = _CollectingWriter()
        observer = WebRuntimeObserver(uuid4(), writer)
        await observer.start(BotConfig(name="test"))
        for count in range(5_000):
            observer.emit(
                StreamHealth(
                    queue_depth=count % 4,
                    peak_queue_depth=4,
                    book_dispatch_lag_ms=count,
                    book_stale=False,
                    occurred_at_monotonic_seconds=float(count),
                    book_received_count=count + 10,
                    book_coalesced_count=count,
                )
            )
        await observer.stop()
        return writer.events

    events = asyncio.run(scenario())

    assert [event.kind for event in events] == [
        EventKind.CHART_SAMPLE,
        EventKind.STREAM_HEALTH,
    ]
    health = events[1].payload
    assert health.queue_depth == 3
    assert health.book_dispatch_lag_ms == 4_999
    assert health.book_received_count == 5_009
    assert health.book_coalesced_count == 4_999


def test_observer_drops_overflow_but_preserves_final_stream_health() -> None:
    async def scenario() -> list[EventKind]:
        writer = _CollectingWriter()
        observer = WebRuntimeObserver(uuid4(), writer, max_pending_events=1)
        await observer.start(BotConfig(name="test"))
        observer.emit(RuntimeFailed("accepted", 1.0))
        observer.emit(RuntimeFailed("overflow", 2.0))
        observer.emit(StreamHealth(1, 2, 3, False, 3.0, 4, 1))
        await observer.stop()
        return [event.kind for event in writer.events]

    assert asyncio.run(scenario()) == [
        EventKind.RUN_FAILURE,
        EventKind.CHART_SAMPLE,
        EventKind.STREAM_HEALTH,
    ]


def test_terminal_and_web_share_dashboard_semantics() -> None:
    config = BotConfig(name="parity", event_max_age_ms=100)
    terminal = DashboardState(
        require_accepted_books=True,
        book_max_age_ms=config.event_max_age_ms,
        initial_cash_usdc=config.paper_portfolio_usdc,
    )
    browser = DashboardProjection.from_config(config)
    book = _book()
    book_item = BookStreamEvent(StreamKind.BOOK, book)
    wallet_item = WalletStreamEvent(StreamKind.WALLET, _wallet_trade())
    fill = FillEvent(
        order_id="order",
        token_id=book.token_id,
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("1"),
        filled_size=Decimal("1"),
        average_price=Decimal("0.5"),
        fee_usdc=Decimal("0"),
        received_at_ms=1_000,
    )
    portfolio = PortfolioSnapshot(
        Decimal("99.5"),
        Decimal("0"),
        (PortfolioPositionSnapshot(book.token_id, Decimal("1"), Decimal("0.5")),),
    )
    events = (
        StreamReceived(book_item, 1.0),
        DispatchCompleted(book_item, DispatchOutcome.accepted_event(), 1.0),
        FillCompleted(_order(), fill, portfolio, 1, 1.0),
        StreamReceived(wallet_item, 1.0),
        DispatchCompleted(wallet_item, DispatchOutcome.accepted_event(), 1.0),
    )
    for event in events:
        terminal.apply(event)
        browser.apply(event)

    terminal_sample = terminal.projection.sample(1_000)
    assert terminal_sample == browser.sample(1_000)
    assert terminal_sample.markets[0].value == Decimal("0.5")
    assert terminal_sample.markets[0].markers == (Side.BUY,)
    assert terminal_sample.equity.value == Decimal("99.9")
    terminal_wallet = terminal.projection.wallet_point(_wallet_trade().source_key)
    assert terminal_wallet == browser.wallet_point(_wallet_trade().source_key)
    assert terminal_wallet is not None
    assert terminal_wallet.notional == Decimal("0.5")
    assert terminal_wallet.accepted is True

    gap = StreamReceived(
        BookGapStreamEvent(
            StreamKind.BOOK_GAP,
            BookGapEvent("condition", 1_050, BookGapReason.BOOK_STREAM_GAP),
        ),
        2.0,
    )
    for projection in (terminal, browser):
        projection.apply(gap)
    terminal_gap = terminal.projection.sample(1_100)
    browser_gap = browser.sample(1_100)

    assert terminal_gap == browser_gap
    assert terminal_gap.markets[0].status is ValuationStatus.STALE
    assert terminal_gap.equity.status is ValuationStatus.STALE

    settlement = _settlement(portfolio)
    terminal.apply(settlement)
    browser.apply(settlement)
    assert terminal.projection.sample(1_200) == browser.sample(1_200)
    assert tuple(terminal.chart_tokens) == ()


def test_observer_cadence_and_persistence_classification() -> None:
    async def scenario():
        clock = _ControlledClock()
        writer = _CollectingWriter()
        config = BotConfig(
            name="cadence",
            paper_portfolio_usdc=Decimal("125.50"),
        )
        observer = WebRuntimeObserver(
            uuid4(),
            writer,
            sleep=clock.sleep,
            now_ms=clock.now_ms,
            now_utc=clock.now_utc,
        )
        await observer.start(config)
        observer.emit(StreamHealth(1, 2, 3, False, 1.0, 4, 1))
        for _ in range(4):
            clock.advance()
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await observer.stop()
        return clock, writer, config.paper_portfolio_usdc

    clock, writer, initial_cash_usdc = asyncio.run(scenario())

    assert clock.delays == [CHART_SAMPLE_INTERVAL_SECONDS] * 5
    assert [event.kind for event in writer.live_events].count(
        LiveEventKind.CHART_MARKET
    ) == 4
    assert [event.kind for event in writer.live_events].count(
        LiveEventKind.CHART_EQUITY
    ) == 4
    assert [event.kind for event in writer.live_events].count(
        LiveEventKind.CHART_WALLET
    ) == 4
    assert [event.kind for event in writer.live_events].count(
        LiveEventKind.STREAM_HEALTH
    ) == 1
    live_equity_events = [
        event
        for event in writer.live_events
        if event.kind is LiveEventKind.CHART_EQUITY
    ]
    assert all(
        event.payload.point.value == initial_cash_usdc
        and event.payload.point.status is ValuationStatus.FRESH
        for event in live_equity_events
    )
    assert [event.kind for event in writer.events] == [
        EventKind.CHART_SAMPLE,
        EventKind.CHART_SAMPLE,
        EventKind.STREAM_HEALTH,
    ]
    assert writer.events[0].payload.equity.value == initial_cash_usdc
    assert writer.events[0].payload.equity.status is ValuationStatus.FRESH


def test_observer_keeps_sampling_when_live_publication_fails() -> None:
    async def scenario() -> list[EventKind]:
        clock = _ControlledClock()
        writer = _CollectingWriter(fail_live=True)
        observer = WebRuntimeObserver(
            uuid4(),
            writer,
            sleep=clock.sleep,
            now_ms=clock.now_ms,
            now_utc=clock.now_utc,
        )
        await observer.start(BotConfig(name="fail-open"))
        observer.emit(StreamHealth(1, 2, 3, False, 1.0, 4, 1))
        for _ in range(4):
            clock.advance()
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await observer.stop()
        return [event.kind for event in writer.events]

    assert asyncio.run(scenario()) == [
        EventKind.CHART_SAMPLE,
        EventKind.CHART_SAMPLE,
        EventKind.STREAM_HEALTH,
    ]


def test_observer_publishes_wallet_points_and_persists_each_fill_marker_once() -> None:
    skipped_trade = replace(
        _wallet_trade(),
        wallet="0x0000000000000000000000000000000000000002",
        source_id="skipped",
    )

    async def scenario() -> _CollectingWriter:
        clock = _ControlledClock()
        writer = _CollectingWriter()
        observer = WebRuntimeObserver(
            uuid4(),
            writer,
            sleep=clock.sleep,
            now_ms=clock.now_ms,
            now_utc=clock.now_utc,
        )
        await observer.start(BotConfig(name="dashboard-events"))
        book_item = BookStreamEvent(
            StreamKind.BOOK,
            replace(_book(), received_at_ms=0),
        )
        rejected_book_item = BookStreamEvent(
            StreamKind.BOOK,
            replace(_book(), token_id="rejected-token", received_at_ms=0),
        )
        wallet_item = WalletStreamEvent(StreamKind.WALLET, _wallet_trade())
        skipped_wallet_item = WalletStreamEvent(
            StreamKind.WALLET,
            skipped_trade,
        )
        portfolio = PortfolioSnapshot(
            Decimal("99.5"),
            Decimal("0"),
            (PortfolioPositionSnapshot("token", Decimal("1"), Decimal("0.5")),),
        )
        fill = FillEvent(
            order_id="order",
            token_id="token",
            side=Side.BUY,
            status=OrderStatus.FILLED,
            requested_size=Decimal("1"),
            filled_size=Decimal("1"),
            average_price=Decimal("0.5"),
            fee_usdc=Decimal("0"),
            received_at_ms=1,
        )
        rejected_fill = FillEvent(
            order_id="rejected-order",
            token_id="rejected-token",
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
        for event in (
            StreamReceived(book_item, 1.0),
            DispatchCompleted(book_item, DispatchOutcome.accepted_event(), 1.0),
            StreamReceived(rejected_book_item, 1.0),
            DispatchCompleted(
                rejected_book_item,
                DispatchOutcome.accepted_event(),
                1.0,
            ),
            FillCompleted(
                replace(_order(), token_id="rejected-token"),
                rejected_fill,
                portfolio,
                1,
                1.0,
            ),
            FillCompleted(_order(), fill, portfolio, 1, 1.0),
            StreamReceived(wallet_item, 1.0),
            DispatchCompleted(wallet_item, DispatchOutcome.accepted_event(), 1.0),
            StreamReceived(skipped_wallet_item, 1.0),
            DispatchCompleted(
                skipped_wallet_item,
                DispatchOutcome.skipped(DispatchSkipReason.WALLET_NOT_TRACKED),
                1.0,
            ),
        ):
            observer.emit(event)
        for _ in range(8):
            clock.advance()
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        await observer.stop()
        return writer

    writer = asyncio.run(scenario())
    wallet_events = [
        event
        for event in writer.live_events
        if event.kind is LiveEventKind.CHART_WALLET and event.payload.points
    ]
    chart_samples = [
        event for event in writer.events if event.kind is EventKind.CHART_SAMPLE
    ]

    assert len(wallet_events) == 1
    assert {
        point.source_key: point.accepted
        for point in wallet_events[0].payload.points
    } == {
        _wallet_trade().source_key: True,
        skipped_trade.source_key: False,
    }
    markers_by_token = [
        {point.token_id: point.markers for point in sample.payload.markets}
        for sample in chart_samples
    ]
    assert [markers["token"] for markers in markers_by_token] == [
        (Side.BUY,),
        (),
        (),
    ]
    assert [markers["rejected-token"] for markers in markers_by_token] == [
        (),
        (),
        (),
    ]


def test_event_writer_publishes_only_after_committed_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    event, = project_runtime_event_to_durable(
        uuid4(),
        RuntimeFailed("failure", 1.0),
    )

    class Store:
        def __init__(self, session) -> None:
            return None

        async def append(self, received):
            calls.append(("append", received))
            return received.model_copy(update={"id": 7})

    class Redis:
        async def publish(self, channel, message):
            calls.append((channel, message))

    monkeypatch.setattr(event_writer_module, "EventStore", Store)

    stored = asyncio.run(
        RunEventWriter(_SessionFactory(), Redis()).append(event)
    )

    assert stored.id == 7
    assert calls == [
        ("append", event),
        (run_event_channel(event.run_id), "7"),
    ]


def test_event_store_rejects_an_id_outside_the_public_cursor_range() -> None:
    event, = project_runtime_event_to_durable(
        uuid4(),
        RuntimeFailed("failure", 1.0),
    )

    class Session:
        def __init__(self) -> None:
            self.row = None
            self.rolled_back = False

        def add(self, row) -> None:
            self.row = row

        async def flush(self) -> None:
            self.row.id = MAX_DURABLE_EVENT_ID + 1

        async def rollback(self) -> None:
            self.rolled_back = True

        async def commit(self) -> None:
            raise AssertionError("out-of-range event must not commit")

    session = Session()
    with pytest.raises(ValueError, match="public cursor range"):
        asyncio.run(EventStore(session).append(event))  # type: ignore[arg-type]

    assert session.rolled_back


class _CollectingWriter:
    def __init__(self, *, fail: bool = False, fail_live: bool = False) -> None:
        self.events: list[DurableEvent] = []
        self.live_events = []
        self._fail = fail
        self._fail_live = fail_live

    async def append(self, event):
        self.events.append(event)
        if self._fail:
            raise RuntimeError("writer unavailable")
        return event

    async def publish_live(self, event):
        self.live_events.append(event)
        if self._fail_live:
            raise RuntimeError("live publisher unavailable")


class _ControlledClock:
    def __init__(self) -> None:
        self._ticks: asyncio.Queue[None] = asyncio.Queue()
        self.delays: list[float] = []
        self.milliseconds = 0

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        await self._ticks.get()
        self.milliseconds += round(delay * 1_000)

    def advance(self) -> None:
        self._ticks.put_nowait(None)

    def now_ms(self) -> int:
        return self.milliseconds

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(self.milliseconds / 1_000, UTC)


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, exception_type, exception, traceback):
        return False


def _order() -> OrderRequest:
    return OrderRequest(
        token_id="token",
        side=Side.BUY,
        price=Decimal("0.5"),
        size=Decimal("1"),
    )


def _wallet_trade() -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet="0x0000000000000000000000000000000000000001",
        condition_id="condition",
        token_id="token",
        side=Side.BUY,
        size=Decimal("1"),
        price=Decimal("0.5"),
        source_id="source",
        trade_timestamp_ms=1,
        observed_at_ms=1,
    )


def _book() -> BookSnapshot:
    return BookSnapshot(
        token_id="token",
        bids=(BookLevel(Decimal("0.4"), Decimal("10")),),
        asks=(BookLevel(Decimal("0.6"), Decimal("10")),),
        received_at_ms=1_000,
        market_slug="market",
        condition_id="condition",
        outcome="Up",
    )


def _settlement(portfolio: PortfolioSnapshot) -> MarketSettled:
    resolution = MarketResolutionEvent(
        condition_id="condition",
        market_slug="market",
        token_ids=("token", "other"),
        winning_token_id="token",
        winning_outcome="Up",
        resolved_at_ms=1_200,
        source="test",
    )
    return MarketSettled(
        MarketSettlementEvent(
            resolution=resolution,
            paper_positions=(),
            followed_wallet_positions=(),
            settled_at_ms=1_200,
        ),
        portfolio,
        2.0,
    )
