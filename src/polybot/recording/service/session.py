"""Recording archive-session creation and resume bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from polybot.async_io import run_blocking
from polybot.recording.archive.writer import RecordingArchive
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts.gaps import (
    CoverageGapPayload,
    CoverageGapReason,
)
from polybot.recording.writer import AsyncRecordingWriter

@dataclass(frozen=True, slots=True)
class StartedRecordingSession:
    writer: AsyncRecordingWriter
    started_at_ms: int


async def start_recording_session(
    *,
    output_path: Path,
    target_identity: str,
    resume: bool,
    clock: ObservationClock,
) -> StartedRecordingSession:
    """Open the archive writer and bridge an offline resume interval."""

    started_at_ms = clock.now_ms()
    archive = await run_blocking(
        RecordingArchive.resume if resume else RecordingArchive.create,
        output_path,
        target_identity=target_identity,
        started_at_ms=started_at_ms,
    )
    writer = AsyncRecordingWriter(archive)
    writer.start()
    if resume:
        gap_started_at_ms = archive.resume_from_ms
        if gap_started_at_ms is None:
            raise AssertionError("resumed archive has no prior boundary")
        clock.advance_to(gap_started_at_ms)
        started_at_ms = clock.now_ms()
        await writer.open_gap(
            CoverageGapPayload(
                reason=CoverageGapReason.RECORDER_OFFLINE,
                started_at_ms=gap_started_at_ms,
                ended_at_ms=started_at_ms,
            ),
            observed_at_ms=started_at_ms,
            identity=None,
            subscription_generation=0,
        )
    return StartedRecordingSession(writer=writer, started_at_ms=started_at_ms)
