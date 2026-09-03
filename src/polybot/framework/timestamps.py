"""Dependency-light timestamp preconditions shared across runtime domains."""

NONNEGATIVE_TIMESTAMP_FLOOR = 0


def require_nonnegative_timestamp(value: object, label: str) -> int:
    if not is_nonnegative_timestamp(value):
        raise ValueError(f"{label} must be nonnegative")
    return value


def is_nonnegative_timestamp(value: object) -> bool:
    return not (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < NONNEGATIVE_TIMESTAMP_FLOOR
    )
