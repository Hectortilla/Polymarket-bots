"""Performance sampling cadence contracts."""

from polybot.integers import is_positive_int

DEFAULT_REPORT_INTERVAL_MS = 1_000


def validate_report_interval(value: object) -> None:
    if not is_positive_int(value):
        raise ValueError("report interval must be positive")
