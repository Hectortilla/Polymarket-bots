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

from .. import kinds
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
    kind: Literal[kinds.EventKind.RUN_LIFECYCLE] = kinds.EventKind.RUN_LIFECYCLE
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
    kind: Literal[kinds.EventKind.RUN_BOOTSTRAP] = kinds.EventKind.RUN_BOOTSTRAP
    payload: RunBootstrapPayload


class BotActivityDurableEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.BOT_ACTIVITY] = kinds.EventKind.BOT_ACTIVITY
    payload: BotActivityPayload


class BrokerOrderEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.BROKER_ORDER] = kinds.EventKind.BROKER_ORDER
    payload: BrokerOrderPayload


class BrokerFillEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.BROKER_FILL] = kinds.EventKind.BROKER_FILL
    payload: BrokerFillPayload


class BrokerFailureEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.BROKER_FAILURE] = kinds.EventKind.BROKER_FAILURE
    payload: BrokerFailurePayload


class MarketSettlementDurableEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.MARKET_SETTLEMENT] = kinds.EventKind.MARKET_SETTLEMENT
    payload: MarketSettlementPayload


class PortfolioSnapshotEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.PORTFOLIO_SNAPSHOT] = kinds.EventKind.PORTFOLIO_SNAPSHOT
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
    kind: Literal[kinds.EventKind.WALLET_TIMELINE] = kinds.EventKind.WALLET_TIMELINE
    payload: WalletTimelinePayload


class StreamHealthEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.STREAM_HEALTH] = kinds.EventKind.STREAM_HEALTH
    payload: StreamHealthPayload


class RunFailureEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.RUN_FAILURE] = kinds.EventKind.RUN_FAILURE
    payload: RunFailurePayload


class ChartSampleEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.CHART_SAMPLE] = kinds.EventKind.CHART_SAMPLE
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
    Field(discriminator=kinds.EVENT_DISCRIMINATOR_FIELD),
]


DURABLE_EVENT_ADAPTER = TypeAdapter(DurableEvent)


class PersistedRunLifecycleEvent(RunLifecycleEvent):
    id: DurableEventId


class PersistedRunBootstrapEvent(RunBootstrapEvent):
    id: DurableEventId


class PersistedBotActivityEvent(BotActivityDurableEvent):
    id: DurableEventId


class PersistedBrokerOrderEvent(BrokerOrderEvent):
    id: DurableEventId


class PersistedBrokerFillEvent(BrokerFillEvent):
    id: DurableEventId


class PersistedBrokerFailureEvent(BrokerFailureEvent):
    id: DurableEventId


class PersistedMarketSettlementEvent(MarketSettlementDurableEvent):
    id: DurableEventId


class PersistedPortfolioSnapshotEvent(PortfolioSnapshotEvent):
    id: DurableEventId


class PersistedWalletTimelineEvent(WalletTimelineDurableEvent):
    id: DurableEventId


class PersistedStreamHealthEvent(StreamHealthEvent):
    id: DurableEventId


class PersistedRunFailureEvent(RunFailureEvent):
    id: DurableEventId


class PersistedChartSampleEvent(ChartSampleEvent):
    id: DurableEventId


PERSISTED_DURABLE_EVENT_MODELS = (
    PersistedRunLifecycleEvent,
    PersistedRunBootstrapEvent,
    PersistedBotActivityEvent,
    PersistedBrokerOrderEvent,
    PersistedBrokerFillEvent,
    PersistedBrokerFailureEvent,
    PersistedMarketSettlementEvent,
    PersistedPortfolioSnapshotEvent,
    PersistedWalletTimelineEvent,
    PersistedStreamHealthEvent,
    PersistedRunFailureEvent,
    PersistedChartSampleEvent,
)


type PersistedDurableEvent = Annotated[
    PersistedRunLifecycleEvent
    | PersistedRunBootstrapEvent
    | PersistedBotActivityEvent
    | PersistedBrokerOrderEvent
    | PersistedBrokerFillEvent
    | PersistedBrokerFailureEvent
    | PersistedMarketSettlementEvent
    | PersistedPortfolioSnapshotEvent
    | PersistedWalletTimelineEvent
    | PersistedStreamHealthEvent
    | PersistedRunFailureEvent
    | PersistedChartSampleEvent,
    Field(discriminator=kinds.EVENT_DISCRIMINATOR_FIELD),
]


PERSISTED_DURABLE_EVENT_ADAPTER = TypeAdapter(PersistedDurableEvent)


class LiveEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    occurred_at: AwareDatetime


class LiveMarketChartEvent(LiveEventBase):
    kind: Literal[kinds.LiveEventKind.CHART_MARKET] = kinds.LiveEventKind.CHART_MARKET
    payload: MarketChartPayload


class LiveEquityChartEvent(LiveEventBase):
    kind: Literal[kinds.LiveEventKind.CHART_EQUITY] = kinds.LiveEventKind.CHART_EQUITY
    payload: EquityChartPayload


class LiveWalletChartEvent(LiveEventBase):
    kind: Literal[kinds.LiveEventKind.CHART_WALLET] = kinds.LiveEventKind.CHART_WALLET
    payload: WalletChartPayload


class LiveStreamHealthEvent(LiveEventBase):
    kind: Literal[kinds.LiveEventKind.STREAM_HEALTH] = kinds.LiveEventKind.STREAM_HEALTH
    payload: StreamHealthPayload


LIVE_EVENT_MODELS = (
    LiveMarketChartEvent,
    LiveEquityChartEvent,
    LiveWalletChartEvent,
    LiveStreamHealthEvent,
)


type LiveChartEvent = Annotated[
    LiveMarketChartEvent | LiveEquityChartEvent | LiveWalletChartEvent,
    Field(discriminator=kinds.EVENT_DISCRIMINATOR_FIELD),
]
type LiveRunEvent = Annotated[
    LiveMarketChartEvent
    | LiveEquityChartEvent
    | LiveWalletChartEvent
    | LiveStreamHealthEvent,
    Field(discriminator=kinds.EVENT_DISCRIMINATOR_FIELD),
]


LIVE_RUN_EVENT_ADAPTER = TypeAdapter(LiveRunEvent)
