"""Backtest-readiness policy derived from a recording inspection."""

from __future__ import annotations

from .contracts.session import SessionIntegrityStatus
from .inspection import RecordingInspection


def backtest_readiness_notes(
    inspection: RecordingInspection,
) -> tuple[str, ...]:
    notes: list[str] = []
    if len(inspection.sessions) > 1:
        notes.append("Backtesting requires an explicit --session selection.")
    active_sessions = tuple(
        session.statistics.session.session_id
        for session in inspection.sessions
        if session.statistics.session.integrity_status
        is SessionIntegrityStatus.ACTIVE
    )
    if active_sessions:
        notes.append(
            "Active session(s) "
            + ", ".join(str(value) for value in active_sessions)
            + " are snapshot-only here; stop the recorder before backtesting."
        )
    partial_sessions = tuple(
        session.statistics.session.session_id
        for session in inspection.sessions
        if session.statistics.session.integrity_status
        in (SessionIntegrityStatus.INCOMPLETE, SessionIntegrityStatus.FAILED)
    )
    if partial_sessions:
        notes.append(
            "Partial source session(s): "
            + ", ".join(str(value) for value in partial_sessions)
            + ". Replay defaults to each durable boundary."
        )
    if inspection.gap_count:
        notes.append(
            "Detected gaps require a clean selected range; use recording.trim to "
            "retain the longest all-market clean interval."
        )
    else:
        notes.append(
            "No detected gaps. This does not prove exchange-complete capture."
        )
    if inspection.replay_event_count == 0:
        notes.append("The archive has no replay events.")
    notes.append(
        "The backtester still validates metadata, two-token book bootstrap, "
        "range, and selected-market coverage before running a bot."
    )
    return tuple(notes)
