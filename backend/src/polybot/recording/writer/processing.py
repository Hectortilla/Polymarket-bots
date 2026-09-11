"""Execute queued archive commands and propagate the first writer failure."""

from __future__ import annotations

import asyncio

from polybot.async_io import run_blocking
from polybot.recording.archive.writer import RecordingArchive

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
    set_result,
)


class RecordingCommandProcessor:
    def __init__(
        self,
        archive: RecordingArchive,
        queue: asyncio.Queue[WriterCommand],
        batch_size: int,
    ) -> None:
        self._archive = archive
        self._queue = queue
        self._batch_size = batch_size
        self.failure: BaseException | None = None

    async def run(self) -> None:
        try:
            while True:
                command = await self._queue.get()
                if isinstance(command, EventCommand):
                    if await self._write_event_batch(command):
                        return
                    continue
                if isinstance(command, CheckpointCommand):
                    await self._write_checkpoint(command)
                    continue
                if await self._process_non_event(command):
                    return
        except BaseException as error:
            self.failure = error
            await self._fail_pending(error)
            try:
                await run_blocking(
                    self._archive.close,
                    clean=False,
                    failure_reason=f"{type(error).__name__}: {error}",
                )
            except Exception:
                # Finalization must not replace the failure that stopped recording.
                pass
            if isinstance(error, asyncio.CancelledError):
                raise

    async def _write_event_batch(self, first: EventCommand) -> bool:
        commands = [first]
        event_count = len(first.events)
        while event_count < self._batch_size:
            try:
                candidate = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not isinstance(candidate, EventCommand):
                try:
                    await self._write_events(commands)
                except BaseException as error:
                    set_exception(candidate.completion, error)
                    raise
                return await self._process_non_event(candidate)
            commands.append(candidate)
            event_count += len(candidate.events)
        await self._write_events(commands)
        return False

    async def _process_non_event(self, command: WriterCommand) -> bool:
        if isinstance(command, CheckpointCommand):
            await self._write_checkpoint(command)
            return False
        if isinstance(command, OpenGapCommand):
            await self._open_gap(command)
            return False
        if isinstance(command, CloseGapCommand):
            await self._close_gap(command)
            return False
        if isinstance(command, CaptureAnomalyCommand):
            await self._record_anomaly(command)
            return False
        if isinstance(command, BarrierCommand):
            set_result(command.completion, None)
            return False
        if isinstance(command, StopCommand):
            await self._close(command)
            return True
        raise AssertionError("unexpected recording writer command")

    async def _write_events(self, commands: list[EventCommand]) -> None:
        try:
            await run_blocking(
                self._archive.append_events,
                tuple(event for command in commands for event in command.events),
            )
        except BaseException as error:
            for command in commands:
                set_exception(command.completion, error)
            raise
        for command in commands:
            set_result(command.completion, None)

    async def _write_checkpoint(self, command: CheckpointCommand) -> None:
        try:
            await run_blocking(
                self._archive.append_checkpoints,
                command.checkpoints,
            )
        except BaseException as error:
            set_exception(command.completion, error)
            raise
        set_result(command.completion, None)

    async def _open_gap(self, command: OpenGapCommand) -> None:
        try:
            gap_id = await run_blocking(
                self._archive.append_gap,
                command.event,
            )
        except BaseException as error:
            set_exception(command.completion, error)
            raise
        set_result(command.completion, gap_id)

    async def _close_gap(self, command: CloseGapCommand) -> None:
        try:
            await run_blocking(
                self._archive.close_gap,
                command.gap_id,
                ended_at_ms=command.ended_at_ms,
            )
        except BaseException as error:
            set_exception(command.completion, error)
            raise
        set_result(command.completion, None)

    async def _record_anomaly(self, command: CaptureAnomalyCommand) -> None:
        try:
            record = await run_blocking(
                self._archive.append_capture_anomaly,
                command.anomaly,
                observed_at_ms=command.observed_at_ms,
                identity=command.identity,
                subscription_generation=command.subscription_generation,
            )
        except BaseException as error:
            set_exception(command.completion, error)
            raise
        set_result(command.completion, record)

    async def _close(self, command: StopCommand) -> None:
        try:
            await run_blocking(
                self._archive.close,
                clean=command.clean,
                failure_reason=command.failure_reason,
            )
        except BaseException as error:
            set_exception(command.completion, error)
            raise
        set_result(command.completion, None)

    async def _fail_pending(self, error: BaseException) -> None:
        while True:
            try:
                command = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            set_exception(command.completion, error)
