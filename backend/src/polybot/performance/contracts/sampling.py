"""Performance sampling cadence contracts."""

DEFAULT_REPORT_INTERVAL_MS = 1_000


def validate_report_interval(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("report interval must be positive")
