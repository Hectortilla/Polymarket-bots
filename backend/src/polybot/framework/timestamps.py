"""Dependency-light timestamp preconditions shared across runtime domains."""

MILLISECONDS_PER_SECOND = 1_000
NANOSECONDS_PER_MILLISECOND = 1_000_000
NONNEGATIVE_TIMESTAMP_FLOOR = 0


def require_nonnegative_timestamp_ms(timestamp_ms: object, label: str) -> int:
    if not is_nonnegative_timestamp_ms(timestamp_ms):
        raise ValueError(f"{label} must be nonnegative")
    return timestamp_ms


def is_nonnegative_timestamp_ms(timestamp_ms: object) -> bool:
    return not (
        isinstance(timestamp_ms, bool)
        or not isinstance(timestamp_ms, int)
        or timestamp_ms < NONNEGATIVE_TIMESTAMP_FLOOR
    )


def timestamp_bounds_are_ordered(start_at_ms: int, end_at_ms: int) -> bool:
    """Inclusive interval boundaries must run forward in time."""
    return start_at_ms <= end_at_ms
