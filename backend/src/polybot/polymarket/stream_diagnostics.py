"""Validated diagnostics exposed by official SDK subscription handles."""

from __future__ import annotations

from polybot.polymarket.errors import MarketDataError, MarketDataIssue


SDK_DROPPED_COUNT_ATTRIBUTE = "dropped"
_MISSING = object()


def sdk_dropped_count(handle: object) -> int:
    """Read the SDK drop counter without hiding malformed diagnostics."""
    value = getattr(handle, SDK_DROPPED_COUNT_ATTRIBUTE, _MISSING)
    if value is _MISSING:
        raise MarketDataError(
            MarketDataIssue.INVALID_STREAM_DIAGNOSTICS,
            "market stream is missing the dropped counter",
        )
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise MarketDataError(
        MarketDataIssue.INVALID_STREAM_DIAGNOSTICS,
        "market stream dropped counter must be a nonnegative integer",
    )


def require_monotonic_dropped_count(previous: int, current: int) -> int:
    """Reject a diagnostic reset within one subscription generation."""
    if current < previous:
        raise MarketDataError(
            MarketDataIssue.INVALID_STREAM_DIAGNOSTICS,
            "market stream dropped counter must not decrease",
        )
    return current
