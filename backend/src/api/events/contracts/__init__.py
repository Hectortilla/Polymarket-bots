"""Typed wire contracts for the append-only run event stream."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from polybot.cli.observability.events import PortfolioSnapshot
from polybot.dashboard.contracts import MAX_CHART_TOKENS, DashboardSample
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from api.events.contracts.payloads.base import MAX_JSON_INTEGER, NonNegativeJsonInteger
from api.events.contracts.payloads.broker import (
    BrokerFailurePayload,
    BrokerFillPayload,
    BrokerOrderPayload,
)
from api.events.contracts.payloads.chart import (
    ChartSamplePayload,
    EquityChartPointPayload,
    MarketChartPointPayload,
    WalletTimelinePayload,
)
from api.events.contracts.payloads.lifecycle import (
    BotActivityPayload,
    FeedObservation,
    RunBootstrapPayload,
    RunFailurePayload,
    RunStartedPayload,
    RunStatusPayload,
    StreamHealthPayload,
)
from api.events.contracts.payloads.portfolio import (
    MarketSettlementPayload,
    PortfolioSnapshotPayload,
)
from api.events.ids import (
    FIRST_DURABLE_EVENT_ID,
    MAX_DURABLE_EVENT_ID,
)
from api.runs.status import TERMINAL_RUN_STATUSES, RunStatus

from .. import kinds

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
    kind: Literal[kinds.EventKind.PORTFOLIO_SNAPSHOT] = (
        kinds.EventKind.PORTFOLIO_SNAPSHOT
    )
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

    @classmethod
    def from_observation(
        cls,
        run_id: UUID,
        event: FeedObservation,
    ) -> StreamHealthEvent:
        return StreamHealthEvent(
            run_id=run_id,
            occurred_at=event.observed_at,
            payload=event.health,
        )


class RunFailureEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.RUN_FAILURE] = kinds.EventKind.RUN_FAILURE
    payload: RunFailurePayload


class ChartSampleEvent(DurableEventBase):
    kind: Literal[kinds.EventKind.CHART_SAMPLE] = kinds.EventKind.CHART_SAMPLE
    payload: ChartSamplePayload

    @classmethod
    def from_sample(
        cls,
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


class LiveRunSnapshot(BaseModel):
    """One replaceable display state; annotations are committed durable records."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    occurred_at: AwareDatetime
    kind: Literal[kinds.LiveEventKind.RUN_SNAPSHOT] = kinds.LiveEventKind.RUN_SNAPSHOT
    generation: int = Field(ge=1, le=MAX_JSON_INTEGER)
    sequence: int = Field(ge=1, le=MAX_JSON_INTEGER)
    sampled_at_ms: NonNegativeJsonInteger
    markets: tuple[MarketChartPointPayload, ...] = Field(max_length=MAX_CHART_TOKENS)
    equity: EquityChartPointPayload
    health: FeedObservation | None = None

    @model_validator(mode="after")
    def validate_markets(self) -> LiveRunSnapshot:
        if any(point.markers for point in self.markets):
            raise ValueError("live snapshots cannot contain transient markers")
        if len({point.token_id for point in self.markets}) != len(self.markets):
            raise ValueError("duplicate live market token")
        return self

    @classmethod
    def from_sample(
        cls,
        run_id: UUID,
        sample: DashboardSample,
        *,
        occurred_at: datetime,
        generation: int,
        sequence: int,
        health: FeedObservation | None = None,
    ) -> LiveRunSnapshot:
        return cls(
            run_id=run_id,
            occurred_at=occurred_at,
            generation=generation,
            sequence=sequence,
            sampled_at_ms=sample.sampled_at_ms,
            markets=tuple(
                MarketChartPointPayload.from_point(point).model_copy(
                    update={"markers": ()}
                )
                for point in sample.markets
            ),
            equity=EquityChartPointPayload.from_point(sample.equity),
            health=health,
        )


LIVE_EVENT_MODELS = (LiveRunSnapshot,)
type LiveRunEvent = LiveRunSnapshot
LIVE_RUN_EVENT_ADAPTER = TypeAdapter(LiveRunEvent)
