"""Bounded asynchronous writer for a SQLite recording archive."""

from __future__ import annotations

import asyncio

from polybot.async_io import run_blocking

from ..archive.writer import RecordingArchive
from ..contracts.anomalies import CaptureAnomalyPayload
from ..contracts.book import BookBaselinePayload
from ..contracts.gaps import CoverageGapPayload
from ..contracts.market import MarketIdentity
from ..contracts.payloads import RecordedPayload
from ..contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    RecordedEvent,
)
from .commands import (
    BarrierCommand,
    CaptureAnomalyCommand,
    CheckpointCommand,
    CloseGapCommand,
    EventCommand,
    OpenGapCommand,
    StopCommand,
    WriterCommand,
    set_exception,
)
from .contracts import (
    DEFAULT_RECORDING_WRITE_BATCH_SIZE,
    DEFAULT_RECORDING_WRITE_QUEUE_SIZE,
    RECORDING_WRITE_QUEUE_FULL_MESSAGE,
    OpenedCoverageGap,
    PendingRecordingEvent,
    RecordingCheckpointWrite,
    RecordingEventWrite,
    RecordingWriteError,
    RecordingWriteQueueFullError,
)
from .processing import RecordingCommandProcessor


class AsyncRecordingWriter:
    """Serialize archive mutations without blocking stream consumers."""

    def __init__(
        self,
        archive: RecordingArchive,
        *,
        queue_size: int = DEFAULT_RECORDING_WRITE_QUEUE_SIZE,
        batch_size: int = DEFAULT_RECORDING_WRITE_BATCH_SIZE,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("recording writer queue size must be positive")
        if batch_size <= 0:
            raise ValueError("recording writer batch size must be positive")
        self._archive = archive
        self._queue: asyncio.Queue[WriterCommand] = asyncio.Queue(maxsize=queue_size)
        self._processor = RecordingCommandProcessor(archive, self._queue, batch_size)
        self._next_sequence = archive.next_sequence
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def session_id(self) -> int:
        return self._archive.session_id

    @property
    def next_sequence(self) -> int:
        return self._next_sequence

    @property
    def last_sequence(self) -> int:
        return self._next_sequence - 1

    @property
    def failure(self) -> BaseException | None:
        return self._processor.failure

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._processor.run())

    async def record(
        self,
        payload: RecordedPayload,
        *,
        observed_at_ms: int,
        source_timestamp_ms: int | None,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> RecordedEvent:
        pending = self.enqueue_record(
            payload,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=source_timestamp_ms,
            identity=identity,
            subscription_generation=subscription_generation,
        )
        return await pending.wait()

    def enqueue_record(
        self,
        payload: RecordedPayload,
        *,
        observed_at_ms: int,
        source_timestamp_ms: int | None,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> PendingRecordingEvent:
        """Queue an event without treating it as durably acknowledged."""

        events, completion = self._enqueue_event_batch(
            (
                RecordingEventWrite(
                    payload=payload,
                    observed_at_ms=observed_at_ms,
                    source_timestamp_ms=source_timestamp_ms,
                    identity=identity,
                    subscription_generation=subscription_generation,
                ),
            )
        )
        return PendingRecordingEvent(events[0], completion)

    async def record_batch(
        self,
        writes: tuple[RecordingEventWrite, ...],
    ) -> tuple[RecordedEvent, ...]:
        """Commit one or more semantically coupled events atomically."""

        events, completion = self._enqueue_event_batch(writes)
        await asyncio.shield(completion)
        return events

    async def checkpoint(
        self,
        book: BookBaselinePayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> BookCheckpoint:
        (checkpoint,) = await self.checkpoint_batch(
            (
                RecordingCheckpointWrite(
                    book=book,
                    observed_at_ms=observed_at_ms,
                    identity=identity,
                    subscription_generation=subscription_generation,
                ),
            )
        )
        return checkpoint

    async def checkpoint_batch(
        self,
        writes: tuple[RecordingCheckpointWrite, ...],
    ) -> tuple[BookCheckpoint, ...]:
        """Commit a common set of book checkpoints atomically."""

        self._raise_if_unavailable()
        if not writes:
            raise ValueError("recording checkpoint batch must not be empty")
        sequence = self.last_sequence
        checkpoints = tuple(
            BookCheckpoint(
                sequence=sequence,
                session_id=self.session_id,
                subscription_generation=write.subscription_generation,
                observed_at_ms=write.observed_at_ms,
                identity=write.identity,
                book=write.book,
            )
            for write in writes
        )
        completion: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._put_nowait(CheckpointCommand(checkpoints, completion))
        await asyncio.shield(completion)
        return checkpoints

    async def open_gap(
        self,
        payload: CoverageGapPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> OpenedCoverageGap:
        self._raise_if_unavailable()
        completion: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        event = RecordedEvent(
            sequence=self._next_sequence,
            session_id=self.session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=None,
            identity=identity,
            payload=payload,
        )
        self._put_nowait(OpenGapCommand(event, completion))
        self._next_sequence += 1
        gap_id = await asyncio.shield(completion)
        return OpenedCoverageGap(gap_id=gap_id, event=event)

    async def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        self._raise_if_unavailable()
        completion: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._put_nowait(CloseGapCommand(gap_id, ended_at_ms, completion))
        await asyncio.shield(completion)

    async def record_anomaly(
        self,
        anomaly: CaptureAnomalyPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> CaptureAnomalyRecord:
        """Durably journal a non-replayable capture failure."""

        self._raise_if_unavailable()
        completion: asyncio.Future[CaptureAnomalyRecord] = (
            asyncio.get_running_loop().create_future()
        )
        self._put_nowait(
            CaptureAnomalyCommand(
                anomaly=anomaly,
                observed_at_ms=observed_at_ms,
                identity=identity,
                subscription_generation=subscription_generation,
                completion=completion,
            )
        )
        return await asyncio.shield(completion)

    async def flush(self) -> None:
        self._raise_if_unavailable()
        completion = asyncio.get_running_loop().create_future()
        await asyncio.shield(self._queue.put(BarrierCommand(completion)))
        if self._processor.failure is not None:
            set_exception(completion, self._processor.failure)
        await asyncio.shield(completion)

    async def stop(
        self,
        *,
        clean: bool,
        failure_reason: str | None = None,
    ) -> None:
        if self._stopped:
            if self._task is not None:
                await asyncio.shield(self._task)
            return
        self._stopped = True
        if self._task is None:
            await run_blocking(
                self._archive.close,
                clean=clean,
                failure_reason=failure_reason,
            )
            return
        if self._processor.failure is not None:
            await asyncio.shield(self._task)
            raise RecordingWriteError(
                "recording writer failed"
            ) from self._processor.failure
        completion = asyncio.get_running_loop().create_future()
        await asyncio.shield(
            self._queue.put(StopCommand(clean, failure_reason, completion))
        )
        if self._processor.failure is not None:
            set_exception(completion, self._processor.failure)
        await asyncio.shield(completion)
        await asyncio.shield(self._task)

    def _enqueue_event_batch(
        self,
        writes: tuple[RecordingEventWrite, ...],
    ) -> tuple[tuple[RecordedEvent, ...], asyncio.Future[None]]:
        self._raise_if_unavailable()
        if not writes:
            raise ValueError("recording event batch must not be empty")
        events = tuple(
            RecordedEvent(
                sequence=self._next_sequence + offset,
                session_id=self.session_id,
                subscription_generation=write.subscription_generation,
                observed_at_ms=write.observed_at_ms,
                source_timestamp_ms=write.source_timestamp_ms,
                identity=write.identity,
                payload=write.payload,
            )
            for offset, write in enumerate(writes)
        )
        completion: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._put_nowait(EventCommand(events, completion))
        self._next_sequence += len(events)
        return events, completion

    def _put_nowait(self, command: WriterCommand) -> None:
        try:
            self._queue.put_nowait(command)
        except asyncio.QueueFull as error:
            raise RecordingWriteQueueFullError(
                RECORDING_WRITE_QUEUE_FULL_MESSAGE
            ) from error

    def _raise_if_unavailable(self) -> None:
        if self._stopped:
            raise RecordingWriteError("recording writer is closed")
        if self._processor.failure is not None:
            raise RecordingWriteError(
                "recording writer failed"
            ) from self._processor.failure
        self.start()
