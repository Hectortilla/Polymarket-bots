"""Runtime cadences shared by live capture and replay."""

from typing import Final


STREAM_PLAN_REFRESH_INTERVAL_MS: Final = 1_000
STREAM_PLAN_REFRESH_INTERVAL_SECONDS: Final = (
    STREAM_PLAN_REFRESH_INTERVAL_MS / 1_000
)
RESOLUTION_RECONCILIATION_SECONDS: Final = 30.0
