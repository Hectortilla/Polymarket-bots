"""Shared Rich presentation helpers for recording command-line tools."""

from __future__ import annotations

from rich.console import Console

ACCENT_STYLE = "bright_cyan"
SUCCESS_STYLE = "green"
WARNING_STYLE = "yellow"
DANGER_STYLE = "bold red"
MUTED_STYLE = "dim"


def recording_console() -> Console:
    """Create a console at print time so test and IDE streams stay current."""

    return Console()
