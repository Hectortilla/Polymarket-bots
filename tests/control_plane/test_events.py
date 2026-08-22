import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

import polybot_control_plane.events.writer as event_writer_module
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
from polybot.cli.streams.kinds import StreamKind
from polybot.framework.activity import ActivitySeverity, BotActivityEvent
from polybot.framework.config.mode import BotMode
from polybot.framework.config.models import BotConfig
from polybot.framework.dispatch import DispatchOutcome
from polybot.framework.events import FillEvent, OrderRequest, OrderStatus, Side
from polybot.framework.events.resolutions import (
    MarketResolutionEvent,
    MarketSettlementEvent,
    SettledPosition,
)
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot_control_plane.events.channels import run_event_channel
from polybot_control_plane.events.contracts import (
    DURABLE_EVENT_ADAPTER,
    BrokerOrderPayload,
    DurableEvent,
    DurableEventBase,
    EVENT_DISCRIMINATOR_FIELD,
    EventKind,
    RunLifecycleEvent,
    RunStatusPayload,
    PortfolioSnapshotPayload,
    WalletTimelineDurableEvent,
    WalletTimelinePayload,
)
from polybot_control_plane.events.observer import WebRuntimeObserver
from polybot_control_plane.events.projection import (
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


def test_runtime_projection_maps_every_current_single_event_kind() -> None:
    run_id = uuid4()
    order = _order()
    events = (
        BootstrapProgress(BootstrapPhase.MARKETS, 1, 2, 1.0),
        BotActivityEvent("ready", ActivitySeverity.SUCCESS, 1.0),
        OrderSubmitted(order, 1.0),
        BrokerFailed(order, "rejected", 1.0),
        StreamHealth(1, 2, 3, False, 1.0, 4, 1),
        RuntimeFailed("safe", 1.0),
        DispatchCompleted(
            WalletStreamEvent(kind=StreamKind.WALLET, event=_wallet_trade()),
            DispatchOutcome.accepted_event(),
            1.0,
        ),
    )

    kinds = tuple(
        project_runtime_event_to_durable(run_id, event)[0].kind
        for event in events
    )

    assert kinds == (
        EventKind.RUN_BOOTSTRAP,
        EventKind.BOT_ACTIVITY,
        EventKind.BROKER_ORDER,
        EventKind.BROKER_FAILURE,
        EventKind.STREAM_HEALTH,
        EventKind.RUN_FAILURE,
        EventKind.WALLET_TIMELINE,
    )


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
        await failing_observer.stop()
        return (
            [event.kind for event in collecting.events],
            [event.kind for event in failing.events],
        )

    collected, failed = asyncio.run(scenario())

    assert collected == [EventKind.RUN_FAILURE, EventKind.RUN_FAILURE]
    assert failed == [EventKind.RUN_FAILURE]


def test_observer_drops_overflow_without_blocking_emit() -> None:
    async def scenario() -> list[EventKind]:
        writer = _CollectingWriter()
        observer = WebRuntimeObserver(uuid4(), writer, max_pending_events=1)
        await observer.start(BotConfig(name="test"))
        observer.emit(RuntimeFailed("accepted", 1.0))
        observer.emit(RuntimeFailed("overflow", 2.0))
        await observer.stop()
        return [event.kind for event in writer.events]

    assert asyncio.run(scenario()) == [EventKind.RUN_FAILURE]


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


class _CollectingWriter:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[DurableEvent] = []
        self._fail = fail

    async def append(self, event):
        self.events.append(event)
        if self._fail:
            raise RuntimeError("writer unavailable")
        return event


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
