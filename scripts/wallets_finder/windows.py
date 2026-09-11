from __future__ import annotations

import time
from datetime import datetime, timezone

from polybot.examples.btc_five_minute_market import (
    BTC_FIVE_MINUTE_BUCKET_SECONDS,
    BTC_FIVE_MINUTE_SLUG_PREFIX,
)
from polybot.framework.markets import market_bucket_start_seconds


def current_bucket_start(now_seconds: float | None = None) -> int:
    timestamp_seconds = int(now_seconds if now_seconds is not None else time.time())
    return market_bucket_start_seconds(
        timestamp_seconds, BTC_FIVE_MINUTE_BUCKET_SECONDS
    )


def slug_for_start(start_timestamp_seconds: int) -> str:
    return f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-{start_timestamp_seconds}"


def window_label(slug: str) -> str:
    try:
        timestamp_seconds = int(slug.rsplit("-", 1)[-1])
    except ValueError:
        return slug
    start = datetime.fromtimestamp(timestamp_seconds, timezone.utc)
    end = datetime.fromtimestamp(
        timestamp_seconds + BTC_FIVE_MINUTE_BUCKET_SECONDS,
        timezone.utc,
    )
    return f"{start:%H:%M}-{end:%H:%M} UTC"


def seconds_to_next_window(
    buffer_seconds: int = 10, now_seconds: float | None = None
) -> float:
    current_time_seconds = time.time() if now_seconds is None else now_seconds
    boundary = (
        market_bucket_start_seconds(
            int(current_time_seconds),
            BTC_FIVE_MINUTE_BUCKET_SECONDS,
            bucket_offset=1,
        )
        + buffer_seconds
    )
    return max(1.0, boundary - current_time_seconds)
