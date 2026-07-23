"""Small validation and selection primitives for archive adapters."""

from __future__ import annotations

from .models import RecordingSession


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _sessions_overlapping(
    sessions: tuple[RecordingSession, ...],
    *,
    start_at_ms: int | None,
    end_at_ms: int | None,
    session_id: int | None,
) -> tuple[RecordingSession, ...]:
    if session_id is not None:
        return tuple(
            session for session in sessions if session.session_id == session_id
        )
    return tuple(
        session
        for session in sessions
        if (end_at_ms is None or session.started_at_ms <= end_at_ms)
        and (
            start_at_ms is None
            or session.ended_at_ms is None
            or session.ended_at_ms >= start_at_ms
        )
    )


def _strict_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_strict_int(value: object, name: str) -> int | None:
    return None if value is None else _strict_int(value, name)


def _positive_int(value: object, name: str) -> int:
    parsed = _strict_int(value, name)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _nonnegative_timestamp(value: object, name: str) -> int:
    parsed = _strict_int(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be nonnegative")
    return parsed


def _nonnegative_int(value: object, name: str) -> int:
    return _nonnegative_timestamp(value, name)
