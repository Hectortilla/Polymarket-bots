from __future__ import annotations

import time
from datetime import datetime, timezone

MARKET_WINDOW_DURATION_SECONDS = 300


def current_bucket_start(now: float | None = None) -> int:
    timestamp = int(now if now is not None else time.time())
    return timestamp - timestamp % MARKET_WINDOW_DURATION_SECONDS


def slug_for_start(start_timestamp: int) -> str:
    return f"btc-updown-5m-{start_timestamp}"


def window_label(slug: str) -> str:
    try:
        timestamp = int(slug.rsplit("-", 1)[-1])
    except ValueError:
        return slug
    start = datetime.fromtimestamp(timestamp, timezone.utc)
    end = datetime.fromtimestamp(timestamp + MARKET_WINDOW_DURATION_SECONDS, timezone.utc)
    return f"{start:%H:%M}-{end:%H:%M} UTC"


def seconds_to_next_window(buffer: int = 10, now: float | None = None) -> float:
    current_time = time.time() if now is None else now
    boundary = (
        (int(current_time) // MARKET_WINDOW_DURATION_SECONDS + 1)
        * MARKET_WINDOW_DURATION_SECONDS
        + buffer
    )
    return max(1.0, boundary - current_time)
