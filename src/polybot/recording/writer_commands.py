"""Internal command messages consumed by the asynchronous recording writer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .contracts.anomalies import CaptureAnomalyPayload
from .contracts.market import MarketIdentity
from .contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    RecordedEvent,
)


@dataclass(slots=True)
class EventCommand:
    events: tuple[RecordedEvent, ...]
    completion: asyncio.Future[None]


@dataclass(slots=True)
class CheckpointCommand:
    checkpoints: tuple[BookCheckpoint, ...]
    completion: asyncio.Future[None]


@dataclass(slots=True)
class OpenGapCommand:
    event: RecordedEvent
    completion: asyncio.Future[int]


@dataclass(slots=True)
class CloseGapCommand:
    gap_id: int
    ended_at_ms: int
    completion: asyncio.Future[None]


@dataclass(slots=True)
class CaptureAnomalyCommand:
    anomaly: CaptureAnomalyPayload
    observed_at_ms: int
    identity: MarketIdentity
    subscription_generation: int
    completion: asyncio.Future[CaptureAnomalyRecord]


@dataclass(slots=True)
class BarrierCommand:
    completion: asyncio.Future[None]


@dataclass(slots=True)
class StopCommand:
    clean: bool
    failure_reason: str | None
    completion: asyncio.Future[None]


WriterCommand = (
    EventCommand
    | CheckpointCommand
    | OpenGapCommand
    | CloseGapCommand
    | CaptureAnomalyCommand
    | BarrierCommand
    | StopCommand
)
