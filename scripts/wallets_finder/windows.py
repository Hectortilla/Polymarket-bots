from __future__ import annotations

import time
from datetime import datetime, timezone

from polybot.examples.btc_five_minute_market import (
    BTC_FIVE_MINUTE_BUCKET_SECONDS,
    BTC_FIVE_MINUTE_SLUG_PREFIX,
)
from polybot.framework.markets import market_bucket_start_seconds


def current_bucket_start(now: float | None = None) -> int:
    timestamp = int(now if now is not None else time.time())
    return market_bucket_start_seconds(timestamp, BTC_FIVE_MINUTE_BUCKET_SECONDS)


def slug_for_start(start_timestamp: int) -> str:
    return f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-{start_timestamp}"


def window_label(slug: str) -> str:
    try:
        timestamp = int(slug.rsplit("-", 1)[-1])
    except ValueError:
        return slug
    start = datetime.fromtimestamp(timestamp, timezone.utc)
    end = datetime.fromtimestamp(
        timestamp + BTC_FIVE_MINUTE_BUCKET_SECONDS,
        timezone.utc,
    )
    return f"{start:%H:%M}-{end:%H:%M} UTC"


def seconds_to_next_window(buffer: int = 10, now: float | None = None) -> float:
    current_time = time.time() if now is None else now
    boundary = (
        market_bucket_start_seconds(
            int(current_time),
            BTC_FIVE_MINUTE_BUCKET_SECONDS,
            bucket_offset=1,
        )
        + buffer
    )
    return max(1.0, boundary - current_time)
