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
    RuntimeFailureReason,
    RuntimeStarted,
    RuntimeStateChanged,
    StreamHealth,
)
from polybot.cli.observability.states import RuntimeState
from polybot.cli.streams.contracts import WalletStreamEvent
from polybot.framework.activity import BotActivityEvent

from api.runs.failures import RunFailureReason
from api.runs.status import RunStatus

from ..contracts import (
    BotActivityDurableEvent,
    BotActivityPayload,
    BrokerFailureEvent,
    BrokerFailurePayload,
    BrokerFillEvent,
    BrokerFillPayload,
    BrokerOrderEvent,
    BrokerOrderPayload,
    DurableEvent,
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
    WalletTimelineDurableEvent,
    WalletTimelinePayload,
)

RUNTIME_RUN_STATUS = {
    RuntimeState.STARTING: RunStatus.STARTING,
    RuntimeState.RUNNING: RunStatus.RUNNING,
    RuntimeState.STOPPING: RunStatus.STOPPING,
    RuntimeState.STOPPED: RunStatus.STOPPED,
    RuntimeState.FAILED: RunStatus.FAILED,
}


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
                payload=RunStatusPayload(status=RUNTIME_RUN_STATUS[event.state]),
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
                payload=RunFailurePayload(
                    error=RunFailureReason.TRACKED_MARKET_ALLOWANCE
                    if event.reason is RuntimeFailureReason.TRACKED_MARKET_LIMIT
                    else event.error
                ),
            ),
        )
    if isinstance(event, DispatchCompleted) and isinstance(
        event.item, WalletStreamEvent
    ):
        if event.outcome is not None and event.outcome.is_duplicate:
            return ()
        return (
            WalletTimelineDurableEvent(
                run_id=run_id,
                occurred_at=occurred_at,
                payload=WalletTimelinePayload.from_dispatch(event),
            ),
        )
    # Raw books, market hints, and individual non-wallet dispatch callbacks are
    # deliberately non-durable; later chart cadence owns their aggregation.
    return ()
