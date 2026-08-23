"""Typed wire contracts for the append-only run event stream."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
)

from polybot.cli.observability.events import PortfolioSnapshot
from polybot_control_plane.events.ids import (
    FIRST_DURABLE_EVENT_ID,
    MAX_DURABLE_EVENT_ID,
)
from polybot_control_plane.runs.status import TERMINAL_RUN_STATUSES, RunStatus

from ..kinds import EVENT_DISCRIMINATOR_FIELD, EventKind, LiveEventKind
from .payloads import (
    BotActivityPayload,
    BrokerFailurePayload,
    BrokerFillPayload,
    BrokerOrderPayload,
    ChartSamplePayload,
    EquityChartPayload,
    MarketSettlementPayload,
    MarketChartPayload,
    PortfolioSnapshotPayload,
    RunBootstrapPayload,
    RunFailurePayload,
    RunStartedPayload,
    RunStatusPayload,
    StreamHealthPayload,
    WalletChartPayload,
    WalletTimelinePayload,
)


type DurableEventId = Annotated[
    int,
    Field(ge=FIRST_DURABLE_EVENT_ID, le=MAX_DURABLE_EVENT_ID),
]


class DurableEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: DurableEventId | None = None
    run_id: UUID
    occurred_at: AwareDatetime


class RunLifecycleEvent(DurableEventBase):
    kind: Literal[EventKind.RUN_LIFECYCLE] = EventKind.RUN_LIFECYCLE
    payload: RunStartedPayload | RunStatusPayload

    def is_terminal(self) -> bool:
        return self.payload.status in TERMINAL_RUN_STATUSES

    @classmethod
    def from_terminal_status(
        cls,
        run_id: UUID,
        status: RunStatus,
        *,
        occurred_at: datetime,
    ) -> RunLifecycleEvent:
        if status not in TERMINAL_RUN_STATUSES:
            raise ValueError("terminal lifecycle event requires a terminal status")
        return cls(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=RunStatusPayload(status=status),
        )


class RunBootstrapEvent(DurableEventBase):
    kind: Literal[EventKind.RUN_BOOTSTRAP] = EventKind.RUN_BOOTSTRAP
    payload: RunBootstrapPayload


class BotActivityDurableEvent(DurableEventBase):
    kind: Literal[EventKind.BOT_ACTIVITY] = EventKind.BOT_ACTIVITY
    payload: BotActivityPayload


class BrokerOrderEvent(DurableEventBase):
    kind: Literal[EventKind.BROKER_ORDER] = EventKind.BROKER_ORDER
    payload: BrokerOrderPayload


class BrokerFillEvent(DurableEventBase):
    kind: Literal[EventKind.BROKER_FILL] = EventKind.BROKER_FILL
    payload: BrokerFillPayload


class BrokerFailureEvent(DurableEventBase):
    kind: Literal[EventKind.BROKER_FAILURE] = EventKind.BROKER_FAILURE
    payload: BrokerFailurePayload


class MarketSettlementDurableEvent(DurableEventBase):
    kind: Literal[EventKind.MARKET_SETTLEMENT] = EventKind.MARKET_SETTLEMENT
    payload: MarketSettlementPayload


class PortfolioSnapshotEvent(DurableEventBase):
    kind: Literal[EventKind.PORTFOLIO_SNAPSHOT] = EventKind.PORTFOLIO_SNAPSHOT
    payload: PortfolioSnapshotPayload

    @classmethod
    def from_snapshot(
        cls,
        run_id: UUID,
        snapshot: PortfolioSnapshot,
        *,
        occurred_at: datetime,
    ) -> PortfolioSnapshotEvent:
        return cls(
            run_id=run_id,
            occurred_at=occurred_at,
            payload=PortfolioSnapshotPayload.model_validate(
                snapshot,
                from_attributes=True,
            ),
        )


class WalletTimelineDurableEvent(DurableEventBase):
    kind: Literal[EventKind.WALLET_TIMELINE] = EventKind.WALLET_TIMELINE
    payload: WalletTimelinePayload


class StreamHealthEvent(DurableEventBase):
    kind: Literal[EventKind.STREAM_HEALTH] = EventKind.STREAM_HEALTH
    payload: StreamHealthPayload


class RunFailureEvent(DurableEventBase):
    kind: Literal[EventKind.RUN_FAILURE] = EventKind.RUN_FAILURE
    payload: RunFailurePayload


class ChartSampleEvent(DurableEventBase):
    kind: Literal[EventKind.CHART_SAMPLE] = EventKind.CHART_SAMPLE
    payload: ChartSamplePayload


type DurableEvent = Annotated[
    RunLifecycleEvent
    | RunBootstrapEvent
    | BotActivityDurableEvent
    | BrokerOrderEvent
    | BrokerFillEvent
    | BrokerFailureEvent
    | MarketSettlementDurableEvent
    | PortfolioSnapshotEvent
    | WalletTimelineDurableEvent
    | StreamHealthEvent
    | RunFailureEvent
    | ChartSampleEvent,
    Field(discriminator=EVENT_DISCRIMINATOR_FIELD),
]


DURABLE_EVENT_ADAPTER = TypeAdapter(DurableEvent)


class LiveEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    occurred_at: AwareDatetime


class LiveMarketChartEvent(LiveEventBase):
    kind: Literal[LiveEventKind.CHART_MARKET] = LiveEventKind.CHART_MARKET
    payload: MarketChartPayload


class LiveEquityChartEvent(LiveEventBase):
    kind: Literal[LiveEventKind.CHART_EQUITY] = LiveEventKind.CHART_EQUITY
    payload: EquityChartPayload


class LiveWalletChartEvent(LiveEventBase):
    kind: Literal[LiveEventKind.CHART_WALLET] = LiveEventKind.CHART_WALLET
    payload: WalletChartPayload


class LiveStreamHealthEvent(LiveEventBase):
    kind: Literal[LiveEventKind.STREAM_HEALTH] = LiveEventKind.STREAM_HEALTH
    payload: StreamHealthPayload


LIVE_EVENT_MODELS = (
    LiveMarketChartEvent,
    LiveEquityChartEvent,
    LiveWalletChartEvent,
    LiveStreamHealthEvent,
)


type LiveChartEvent = Annotated[
    LiveMarketChartEvent | LiveEquityChartEvent | LiveWalletChartEvent,
    Field(discriminator=EVENT_DISCRIMINATOR_FIELD),
]
type LiveRunEvent = Annotated[
    LiveMarketChartEvent
    | LiveEquityChartEvent
    | LiveWalletChartEvent
    | LiveStreamHealthEvent,
    Field(discriminator=EVENT_DISCRIMINATOR_FIELD),
]


LIVE_RUN_EVENT_ADAPTER = TypeAdapter(LiveRunEvent)
