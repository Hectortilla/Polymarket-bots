"""Signal handling and cleanup for a recording coordinator."""

from __future__ import annotations

import asyncio

from polybot.framework.lifecycle import install_signal_handlers, set_event_after_seconds
from polybot.polymarket.public_data.recording import RecordingPublicData
from polybot.recording.coordinator import RecordingCoordinator
from polybot.recording.writer import AsyncRecordingWriter


async def run_until_stopped(
    coordinator: RecordingCoordinator,
    *,
    duration_seconds: int | None,
) -> None:
    """Run the coordinator until a signal or optional duration ends it."""
    shutdown = asyncio.Event()
    remove_signal_handlers = install_signal_handlers(shutdown, required=False)
    duration_task = (
        None
        if duration_seconds is None
        else asyncio.create_task(set_event_after_seconds(duration_seconds, shutdown))
    )
    try:
        await coordinator.run(shutdown)
    finally:
        remove_signal_handlers()
        if duration_task is not None:
            duration_task.cancel()
            await asyncio.gather(duration_task, return_exceptions=True)


async def finish_recording(
    coordinator: RecordingCoordinator | None,
    writer: AsyncRecordingWriter | None,
    *,
    clean: bool,
    failure_reason: str | None = None,
    suppress_errors: bool = False,
) -> None:
    """Close recorder resources while preserving the first cleanup failure."""
    cleanup_error: BaseException | None = None
    if coordinator is not None:
        try:
            await coordinator.close()
        except BaseException as error:
            cleanup_error = error
    if writer is not None:
        writer_clean = clean and cleanup_error is None
        writer_reason = failure_reason
        if not writer_clean and writer_reason is None:
            writer_reason = (
                "recording coordinator cleanup failed"
                if cleanup_error is None
                else f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
        try:
            await writer.stop(
                clean=writer_clean,
                failure_reason=writer_reason,
            )
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
    if cleanup_error is not None and not suppress_errors:
        raise cleanup_error


async def close_recording_sources(public_data: RecordingPublicData) -> None:
    """Best-effort close of sources owned by recording orchestration."""
    try:
        await public_data.close()
    except BaseException:
        pass
