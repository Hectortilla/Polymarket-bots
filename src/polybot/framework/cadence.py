"""Runtime cadences shared by live capture and replay."""

from typing import Final


STREAM_PLAN_REFRESH_INTERVAL_MS: Final = 1_000
STREAM_PLAN_REFRESH_INTERVAL_SECONDS: Final = (
    STREAM_PLAN_REFRESH_INTERVAL_MS / 1_000
)
RESOLUTION_RECONCILIATION_SECONDS: Final = 30.0


def advance_deadline_past(deadline: float, interval: float, now: float) -> float:
    """Advance a recurring deadline until it is strictly later than now."""
    while deadline <= now:
        deadline += interval
    return deadline


def next_interval_boundary_ms(now_ms: int, interval_ms: int) -> int:
    """Return the first fixed-width millisecond boundary after now."""
    return ((now_ms // interval_ms) + 1) * interval_ms
