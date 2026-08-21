"""Dependency-light runtime event projection."""

from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from polybot.cli.observability.events import (
    BootstrapProgress, BrokerFailed, FillCompleted, MarketSettled,
    OrderSubmitted, PortfolioSnapshot, RuntimeEvent, RuntimeFailed,
    RuntimeStarted, RuntimeStateChanged, StreamHealth,
)
from polybot.framework.activity import BotActivityEvent

from .contracts import DurableEvent, EventKind


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def project_event(run_id: UUID, event: RuntimeEvent) -> DurableEvent | None:
    kind: EventKind | None = None
    if isinstance(event, (RuntimeStarted, RuntimeStateChanged)):
        kind = EventKind.RUN_LIFECYCLE
    elif isinstance(event, BootstrapProgress):
        kind = EventKind.RUN_BOOTSTRAP
    elif isinstance(event, BotActivityEvent):
        kind = EventKind.BOT_ACTIVITY
    elif isinstance(event, OrderSubmitted):
        kind = EventKind.BROKER_ORDER
    elif isinstance(event, FillCompleted):
        kind = EventKind.BROKER_FILL
    elif isinstance(event, BrokerFailed):
        kind = EventKind.BROKER_FAILURE
    elif isinstance(event, MarketSettled):
        kind = EventKind.MARKET_SETTLEMENT
    elif isinstance(event, PortfolioSnapshot):
        kind = EventKind.PORTFOLIO_SNAPSHOT
    elif isinstance(event, StreamHealth):
        kind = EventKind.STREAM_HEALTH
    elif isinstance(event, RuntimeFailed):
        kind = EventKind.RUN_FAILURE
    if kind is None:
        return None
    payload = _json_value(event)
    if not isinstance(payload, dict):
        raise TypeError("runtime event projection must be an object")
    return DurableEvent(
        run_id=run_id, kind=kind, occurred_at=datetime.now(UTC), payload=payload
    )
