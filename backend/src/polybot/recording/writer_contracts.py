"""Public contracts for the asynchronous recording writer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .contracts.book import BookBaselinePayload
from .contracts.market import MarketIdentity
from .contracts.payloads import RecordedPayload
from .contracts.records import RecordedEvent


DEFAULT_RECORDING_WRITE_QUEUE_SIZE = 4_096
DEFAULT_RECORDING_WRITE_BATCH_SIZE = 256
RECORDING_WRITE_QUEUE_FULL_MESSAGE = "recording write queue is full"


class RecordingWriteError(RuntimeError):
    pass


class RecordingWriteQueueFullError(RecordingWriteError):
    pass


@dataclass(frozen=True, slots=True)
class OpenedCoverageGap:
    gap_id: int
    event: RecordedEvent


@dataclass(frozen=True, slots=True)
class RecordingEventWrite:
    payload: RecordedPayload
    observed_at_ms: int
    source_timestamp_ms: int | None
    identity: MarketIdentity | None
    subscription_generation: int


@dataclass(frozen=True, slots=True)
class RecordingCheckpointWrite:
    book: BookBaselinePayload
    observed_at_ms: int
    identity: MarketIdentity
    subscription_generation: int


@dataclass(frozen=True, slots=True)
class PendingRecordingEvent:
    """One queued event whose sequence is assigned but commit is pending."""

    event: RecordedEvent
    _completion: asyncio.Future[None]

    @property
    def done(self) -> bool:
        return self._completion.done()

    async def wait(self) -> RecordedEvent:
        """Return the event only after its SQLite transaction commits."""

        # Cancelling one capture must not cancel the shared durability acknowledgement.
        await asyncio.shield(self._completion)
        return self.event
