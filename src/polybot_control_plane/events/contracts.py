"""Wire contracts for the append-only run event stream."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from uuid import UUID

RUN_EVENTS_TABLE_NAME = "run_events"
RUN_EVENTS_RUN_ID_INDEX_NAME = "ix_run_events_run_id"
FIRST_EVENT_CURSOR = 0
MAX_PENDING_EVENTS = 256
RUN_EVENT_CHANNEL_PREFIX = "run:"


class EventKind(StrEnum):
    RUN_LIFECYCLE = "run.lifecycle"
    RUN_BOOTSTRAP = "run.bootstrap"
    BOT_ACTIVITY = "bot.activity"
    BROKER_ORDER = "broker.order"
    BROKER_FILL = "broker.fill"
    BROKER_FAILURE = "broker.failure"
    MARKET_SETTLEMENT = "market.settlement"
    PORTFOLIO_SNAPSHOT = "portfolio.snapshot"
    WALLET_TIMELINE = "wallet.timeline"
    STREAM_HEALTH = "stream.health"
    RUN_FAILURE = "run.failure"
    CHART_SAMPLE = "chart.sample"


class DurableEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    run_id: UUID
    kind: EventKind
    occurred_at: datetime
    payload: dict[str, Any]
