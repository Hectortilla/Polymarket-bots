"""Bounded asynchronous writer for a SQLite recording archive."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from polybot.async_io import run_blocking

from .archive.writer import RecordingArchive
from .contracts.book import BookBaselinePayload
from .contracts.records import (
    BookCheckpoint,
    CaptureAnomalyRecord,
    RecordedEvent,
)
from .contracts.anomalies import CaptureAnomalyPayload
from .contracts.gaps import CoverageGapPayload
from .contracts.market import MarketIdentity
from .contracts.payloads import RecordedPayload


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


@dataclass(slots=True)
class _EventCommand:
    events: tuple[RecordedEvent, ...]
    completion: asyncio.Future[None]


@dataclass(slots=True)
class _CheckpointCommand:
    checkpoints: tuple[BookCheckpoint, ...]
    completion: asyncio.Future[None]


@dataclass(slots=True)
class _OpenGapCommand:
    event: RecordedEvent
    completion: asyncio.Future[int]


@dataclass(slots=True)
class _CloseGapCommand:
    gap_id: int
    ended_at_ms: int
    completion: asyncio.Future[None]


@dataclass(slots=True)
class _CaptureAnomalyCommand:
    anomaly: CaptureAnomalyPayload
    observed_at_ms: int
    identity: MarketIdentity
    subscription_generation: int
    completion: asyncio.Future[CaptureAnomalyRecord]


@dataclass(slots=True)
class _BarrierCommand:
    completion: asyncio.Future[None]


@dataclass(slots=True)
class _StopCommand:
    clean: bool
    failure_reason: str | None
    completion: asyncio.Future[None]


_WriterCommand = (
    _EventCommand
    | _CheckpointCommand
    | _OpenGapCommand
    | _CloseGapCommand
    | _CaptureAnomalyCommand
    | _BarrierCommand
    | _StopCommand
)


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
        self._queue: asyncio.Queue[_WriterCommand] = asyncio.Queue(
            maxsize=queue_size
        )
        self._batch_size = batch_size
        self._next_sequence = archive.next_sequence
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
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
        return self._failure

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

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
        completion: asyncio.Future[None] = (
            asyncio.get_running_loop().create_future()
        )
        self._put_nowait(_EventCommand(events, completion))
        self._next_sequence += len(events)
        return events, completion

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
        completion: asyncio.Future[None] = (
            asyncio.get_running_loop().create_future()
        )
        self._put_nowait(_CheckpointCommand(checkpoints, completion))
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
        completion: asyncio.Future[int] = (
            asyncio.get_running_loop().create_future()
        )
        event = RecordedEvent(
            sequence=self._next_sequence,
            session_id=self.session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=None,
            identity=identity,
            payload=payload,
        )
        self._put_nowait(_OpenGapCommand(event, completion))
        self._next_sequence += 1
        gap_id = await asyncio.shield(completion)
        return OpenedCoverageGap(gap_id=gap_id, event=event)

    async def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        self._raise_if_unavailable()
        completion: asyncio.Future[None] = (
            asyncio.get_running_loop().create_future()
        )
        self._put_nowait(_CloseGapCommand(gap_id, ended_at_ms, completion))
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
            _CaptureAnomalyCommand(
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
        await asyncio.shield(self._queue.put(_BarrierCommand(completion)))
        if self._failure is not None:
            _set_exception(completion, self._failure)
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
        if self._failure is not None:
            await asyncio.shield(self._task)
            raise RecordingWriteError("recording writer failed") from self._failure
        completion = asyncio.get_running_loop().create_future()
        await asyncio.shield(
            self._queue.put(_StopCommand(clean, failure_reason, completion))
        )
        if self._failure is not None:
            _set_exception(completion, self._failure)
        await asyncio.shield(completion)
        await asyncio.shield(self._task)

    def _put_nowait(self, command: _WriterCommand) -> None:
        try:
            self._queue.put_nowait(command)
        except asyncio.QueueFull as error:
            raise RecordingWriteQueueFullError(
                RECORDING_WRITE_QUEUE_FULL_MESSAGE
            ) from error

    def _raise_if_unavailable(self) -> None:
        if self._stopped:
            raise RecordingWriteError("recording writer is closed")
        if self._failure is not None:
            raise RecordingWriteError("recording writer failed") from self._failure
        self.start()

    async def _run(self) -> None:
        try:
            while True:
                command = await self._queue.get()
                if isinstance(command, _EventCommand):
                    if await self._write_event_batch(command):
                        return
                    continue
                if isinstance(command, _CheckpointCommand):
                    await self._write_checkpoint(command)
                    continue
                if await self._process_non_event(command):
                    return
        except BaseException as error:
            self._failure = error
            await self._fail_pending(error)
            try:
                await run_blocking(
                    self._archive.close,
                    clean=False,
                    failure_reason=f"{type(error).__name__}: {error}",
                )
            except Exception:
                pass
            if isinstance(error, asyncio.CancelledError):
                raise

    async def _write_event_batch(self, first: _EventCommand) -> bool:
        commands = [first]
        event_count = len(first.events)
        while event_count < self._batch_size:
            try:
                candidate = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not isinstance(candidate, _EventCommand):
                try:
                    await self._write_events(commands)
                except BaseException as error:
                    _set_command_exception(candidate, error)
                    raise
                return await self._process_non_event(candidate)
            commands.append(candidate)
            event_count += len(candidate.events)
        await self._write_events(commands)
        return False

    async def _write_events(self, commands: list[_EventCommand]) -> None:
        try:
            await run_blocking(
                self._archive.append_events,
                tuple(
                    event
                    for command in commands
                    for event in command.events
                ),
            )
        except BaseException as error:
            for command in commands:
                _set_exception(command.completion, error)
            raise
        for command in commands:
            _set_result(command.completion, None)

    async def _write_checkpoint(self, command: _CheckpointCommand) -> None:
        try:
            await run_blocking(
                self._archive.append_checkpoints,
                command.checkpoints,
            )
        except BaseException as error:
            _set_exception(command.completion, error)
            raise
        _set_result(command.completion, None)

    async def _process_non_event(self, command: _WriterCommand) -> bool:
        if isinstance(command, _CheckpointCommand):
            await self._write_checkpoint(command)
            return False
        if isinstance(command, _OpenGapCommand):
            await self._open_gap(command)
            return False
        if isinstance(command, _CloseGapCommand):
            await self._close_gap(command)
            return False
        if isinstance(command, _CaptureAnomalyCommand):
            await self._record_anomaly(command)
            return False
        if isinstance(command, _BarrierCommand):
            _set_result(command.completion, None)
            return False
        if isinstance(command, _StopCommand):
            await self._close(command)
            return True
        raise AssertionError("unexpected recording writer command")

    async def _open_gap(self, command: _OpenGapCommand) -> None:
        try:
            gap_id = await run_blocking(
                self._archive.append_gap,
                command.event,
            )
        except BaseException as error:
            _set_exception(command.completion, error)
            raise
        _set_result(command.completion, gap_id)

    async def _close_gap(self, command: _CloseGapCommand) -> None:
        try:
            await run_blocking(
                self._archive.close_gap,
                command.gap_id,
                ended_at_ms=command.ended_at_ms,
            )
        except BaseException as error:
            _set_exception(command.completion, error)
            raise
        _set_result(command.completion, None)

    async def _record_anomaly(self, command: _CaptureAnomalyCommand) -> None:
        try:
            record = await run_blocking(
                self._archive.append_capture_anomaly,
                command.anomaly,
                observed_at_ms=command.observed_at_ms,
                identity=command.identity,
                subscription_generation=command.subscription_generation,
            )
        except BaseException as error:
            _set_exception(command.completion, error)
            raise
        _set_result(command.completion, record)

    async def _close(self, command: _StopCommand) -> None:
        try:
            await run_blocking(
                self._archive.close,
                clean=command.clean,
                failure_reason=command.failure_reason,
            )
        except BaseException as error:
            _set_exception(command.completion, error)
            raise
        _set_result(command.completion, None)

    async def _fail_pending(self, error: BaseException) -> None:
        while True:
            try:
                command = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            _set_exception(command.completion, error)


def _set_command_exception(
    command: _WriterCommand,
    error: BaseException,
) -> None:
    _set_exception(command.completion, error)


def _set_result(completion: asyncio.Future, value: object) -> None:
    if not completion.done():
        completion.set_result(value)


def _set_exception(
    completion: asyncio.Future,
    error: BaseException,
) -> None:
    if not completion.done():
        completion.set_exception(error)
