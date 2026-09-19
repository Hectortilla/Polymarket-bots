"""Fixed-cardinality live-path counters, gauges and aggregate durations."""

from collections import Counter
from enum import StrEnum

from api.operations.observations.contracts import LiveTelemetryObservation
from api.operations.observations.sink import OPERATION_LOG


class LiveMetric(StrEnum):
    REFRESH = "refresh"
    REFRESH_FAILURE = "refresh_failure"
    REFRESH_SECONDS = "refresh_seconds"
    SQL_QUERIES = "sql_queries"
    SUPPRESSED = "suppressed"
    COALESCED = "coalesced"
    OVERSIZED = "oversized"
    PUBLISHED = "published"
    PUBLISHED_BYTES = "published_bytes"
    PUBLISH_SECONDS = "publish_seconds"
    HEALTH_WRITTEN = "health_written"
    HEALTH_REJECTED = "health_rejected"
    REDIS_FAILURE = "redis_failure"
    INTEREST_FAILURE = "interest_failure"
    INVALID_FRAME = "invalid_frame"
    RECONNECT = "reconnect"
    SLOW_CLIENT = "slow_client"
    SNAPSHOT_AGE_SECONDS = "snapshot_age_seconds"
    REGISTRATIONS = "registrations"
    PENDING = "pending"
    PENDING_HEALTH = "pending_health"
    INFLIGHT = "inflight"
    VIEWERS = "viewers"
    SUBSCRIPTION_CONNECTIONS = "subscription_connections"
    EVENT_LOOP_LAG_SECONDS = "event_loop_lag_seconds"


class LiveMetrics:
    def __init__(self) -> None:
        self._values: Counter[str] = Counter()

    def increment(self, metric: LiveMetric, amount: int = 1) -> None:
        self._values[metric.value] += amount

    def gauge(self, metric: LiveMetric, value: float) -> None:
        self._values[metric.value] = value

    def observe(self, metric: LiveMetric, value: float) -> None:
        self._values[f"{metric.value}_count"] += 1
        self._values[f"{metric.value}_sum"] += value
        key = f"{metric.value}_max"
        self._values[key] = max(self._values[key], value)

    def snapshot(self) -> dict[str, float]:
        return dict(self._values)

    def emit(self, source: str) -> None:
        OPERATION_LOG.emit(LiveTelemetryObservation(source, self.snapshot()))
