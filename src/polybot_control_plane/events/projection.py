"""Presentation-neutral runtime-to-durable event projection."""

from datetime import UTC, datetime
from uuid import UUID

from polybot.cli.observability.events import (
    BootstrapProgress,
    BrokerFailed,
    DispatchCompleted,
    FillCompleted,
    MarketSettled,
    OrderSubmitted,
    RuntimeEvent,
    RuntimeFailed,
    RuntimeStarted,
    RuntimeStateChanged,
    StreamHealth,
)
from polybot.cli.observability.states import RuntimeState
from polybot.cli.streams.contracts import WalletStreamEvent
from polybot.dashboard.contracts import DashboardSample, WalletChartPoint
from polybot.dashboard.wallets import wallet_chart_point
from polybot.framework.activity import BotActivityEvent
from polybot_control_plane.runs.status import RunStatus

from .contracts import (
    BotActivityDurableEvent,
    BotActivityPayload,
    BrokerFailureEvent,
    BrokerFailurePayload,
    BrokerFillEvent,
    BrokerFillPayload,
    BrokerOrderEvent,
    BrokerOrderPayload,
    ChartSampleEvent,
    ChartSamplePayload,
    DurableEvent,
    EquityChartPayload,
    LiveEquityChartEvent,
    LiveMarketChartEvent,
    LiveRunEvent,
    LiveStreamHealthEvent,
    LiveWalletChartEvent,
    MarketChartPayload,
    MarketSettlementDurableEvent,
    MarketSettlementPayload,
    PortfolioSnapshotEvent,
    RunBootstrapEvent,
    RunBootstrapPayload,
    RunFailureEvent,
    RunFailurePayload,
    RunLifecycleEvent,
    RunStartedPayload,
    RunStatusPayload,
    StreamHealthEvent,
    StreamHealthPayload,
    WalletTimelineDurableEvent,
    WalletTimelinePayload,
    WalletChartPayload,
)
from .contracts.payloads import WalletChartPointPayload


def project_runtime_event_to_durable(
    run_id: UUID,
    event: RuntimeEvent,
) -> tuple[DurableEvent, ...]:
    if isinstance(event, StreamHealth):
        # The observer owns terminal-only coalescing for this high-rate input.
        return ()
    occurred_at = datetime.now(UTC)
    if isinstance(event, RuntimeStarted):
        return (
            RunLifecycleEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=RunStartedPayload(
                    name=event.name,
                    mode=event.mode,
                    initial_cash_usdc=event.initial_cash_usdc,
                ),
            ),
        )
    if isinstance(event, RuntimeStateChanged):
        # The worker writes the authoritative terminal outcome after the
        # observer drains, so runtime STOPPED cannot mask INTERRUPTED/FAILED.
        if event.state is RuntimeState.STOPPED:
            return ()
        return (
            RunLifecycleEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=RunStatusPayload(status=RunStatus(event.state.value)),
            ),
        )
    if isinstance(event, BootstrapProgress):
        return (
            RunBootstrapEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=RunBootstrapPayload(
                    phase=event.phase,
                    completed=event.completed,
                    total=event.total,
                ),
            ),
        )
    if isinstance(event, BotActivityEvent):
        return (
            BotActivityDurableEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=BotActivityPayload(
                    message=event.message,
                    severity=event.severity,
                ),
            ),
        )
    if isinstance(event, OrderSubmitted):
        return (
            BrokerOrderEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=BrokerOrderPayload(order=event.order),
            ),
        )
    if isinstance(event, FillCompleted):
        projected: list[DurableEvent] = [
            BrokerFillEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=BrokerFillPayload(
                    order=event.order,
                    fill=event.fill,
                    portfolio=event.portfolio,
                    latency_ms=event.latency_ms,
                ),
            )
        ]
        if event.portfolio is not None:
            projected.append(
                PortfolioSnapshotEvent.from_snapshot(
                    run_id,
                    event.portfolio,
                    occurred_at=occurred_at,
                )
            )
        return tuple(projected)
    if isinstance(event, BrokerFailed):
        return (
            BrokerFailureEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=BrokerFailurePayload(order=event.order, error=event.error),
            ),
        )
    if isinstance(event, MarketSettled):
        return (
            MarketSettlementDurableEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=MarketSettlementPayload(
                    settlement=event.settlement,
                    portfolio=event.portfolio,
                ),
            ),
            PortfolioSnapshotEvent.from_snapshot(
                run_id,
                event.portfolio,
                occurred_at=occurred_at,
            ),
        )
    if isinstance(event, RuntimeFailed):
        return (
            RunFailureEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=RunFailurePayload(error=event.error),
            ),
        )
    if isinstance(event, DispatchCompleted) and isinstance(
        event.item, WalletStreamEvent
    ):
        return (
            WalletTimelineDurableEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=_wallet_timeline_payload(event),
            ),
        )
    # Raw books, market hints, and individual non-wallet dispatch callbacks are
    # deliberately non-durable; later chart cadence owns their aggregation.
    return ()


def _wallet_timeline_payload(event: DispatchCompleted) -> WalletTimelinePayload:
    trade = event.item.event
    accepted = None if event.outcome is None else event.outcome.accepted
    return WalletTimelinePayload(
        trade=trade,
        outcome=event.outcome,
        point=WalletChartPointPayload.from_point(
            wallet_chart_point(trade, accepted=accepted)
        ),
    )


def project_terminal_stream_health(
    run_id: UUID,
    event: StreamHealth,
) -> StreamHealthEvent:
    return StreamHealthEvent(
        run_id=run_id,
        occurred_at=datetime.now(UTC),
        payload=StreamHealthPayload(
            queue_depth=event.queue_depth,
            peak_queue_depth=event.peak_queue_depth,
            book_dispatch_lag_ms=event.book_dispatch_lag_ms,
            book_stale=event.book_stale,
            book_received_count=event.book_received_count,
            book_coalesced_count=event.book_coalesced_count,
        ),
    )


def project_chart_sample(
    run_id: UUID,
    sample: DashboardSample,
    *,
    occurred_at: datetime,
) -> ChartSampleEvent:
    return ChartSampleEvent(
        run_id=run_id,
        occurred_at=occurred_at,
        payload=ChartSamplePayload.from_sample(sample),
    )


def project_live_chart_events(
    run_id: UUID,
    sample: DashboardSample,
    wallet_points: tuple[WalletChartPoint, ...],
    *,
    occurred_at: datetime,
) -> tuple[LiveRunEvent, ...]:
    return (
        LiveMarketChartEvent(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=MarketChartPayload.from_sample(sample),
        ),
        LiveEquityChartEvent(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=EquityChartPayload.from_sample(sample),
        ),
        LiveWalletChartEvent(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=WalletChartPayload(
                sampled_at_ms=sample.sampled_at_ms,
                points=tuple(
                    WalletChartPointPayload.from_point(point)
                    for point in wallet_points
                ),
            ),
        ),
    )


def project_live_stream_health(
    run_id: UUID,
    event: StreamHealth,
    *,
    occurred_at: datetime,
) -> LiveStreamHealthEvent:
    durable_health_event = project_terminal_stream_health(run_id, event)
    return LiveStreamHealthEvent(
        run_id=run_id,
        occurred_at=occurred_at,
        payload=durable_health_event.payload,
    )
