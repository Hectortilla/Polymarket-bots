"""Shared Rich presentation helpers for recording command-line tools."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console


ACCENT_STYLE = "bright_cyan"
SUCCESS_STYLE = "green"
WARNING_STYLE = "yellow"
DANGER_STYLE = "bold red"
MUTED_STYLE = "dim"


def recording_console() -> Console:
    """Create a console at print time so test and IDE streams stay current."""

    return Console()


def format_timestamp(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return "n/a"
    return (
        datetime.fromtimestamp(timestamp_ms / 1_000, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def format_duration(duration_ms: int) -> str:
    remaining_seconds, milliseconds = divmod(duration_ms, 1_000)
    hours, remaining_seconds = divmod(remaining_seconds, 3_600)
    minutes, seconds = divmod(remaining_seconds, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    if milliseconds:
        parts.append(f"{seconds}.{milliseconds:03d}s")
    else:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def format_bytes(size_bytes: int) -> str:
    value = float(size_bytes)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if value < 1_024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1_024
    raise AssertionError("byte unit selection is unreachable")
