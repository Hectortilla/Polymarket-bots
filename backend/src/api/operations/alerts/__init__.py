"""The operational alert catalog, evaluated without starting services."""

from api.events.health.policy import FEED_TTL_SECONDS
from api.limits.policy import PAPER_BETA
from api.operations.alerts.contracts import AlertDefinition, ThresholdDirection
from api.operations.alerts.policy import (
    ADMISSION_ALERT_COUNT,
    DATABASE_SIZE_ALERT_BYTES,
    DISK_FREE_ALERT_BYTES,
    FEED_LAG_ALERT_MS,
    HTTP_ERROR_ALERT_COUNT,
    NO_AVAILABLE_PROBE_THRESHOLD,
    QUEUE_AGE_ALERT_SECONDS,
)
from api.operations.observations.contracts import AlertCode
from api.operations.telemetry.presence_policy import PRESENCE_TTL_SECONDS
from api.runs.lease_policy import DEFAULT_LEASE_SECONDS

ALERT_DEFINITIONS = {
    definition.code: definition
    for definition in (
        AlertDefinition(
            AlertCode.DATABASE_UNAVAILABLE,
            NO_AVAILABLE_PROBE_THRESHOLD,
            "successful probes",
            ThresholdDirection.UNAVAILABLE,
            "Check private PostgreSQL health and disk; do not resume admissions until reads succeed.",
        ),
        AlertDefinition(
            AlertCode.CONTROL_UNAVAILABLE,
            NO_AVAILABLE_PROBE_THRESHOLD,
            "required control rows",
            ThresholdDirection.UNAVAILABLE,
            "Keep admission closed; repair the required control singleton using a reviewed forward migration.",
        ),
        AlertDefinition(
            AlertCode.REDIS_UNAVAILABLE,
            NO_AVAILABLE_PROBE_THRESHOLD,
            "successful probes",
            ThresholdDirection.UNAVAILABLE,
            "Restore private Redis; queued rows remain durable. Check recovery delivery afterward.",
        ),
        AlertDefinition(
            AlertCode.TELEMETRY_INVALID,
            NO_AVAILABLE_PROBE_THRESHOLD,
            "valid telemetry probes",
            ThresholdDirection.UNAVAILABLE,
            "Inspect private telemetry records and worker configuration; malformed presence or counters cannot prove health.",
        ),
        AlertDefinition(
            AlertCode.STORAGE_UNAVAILABLE,
            NO_AVAILABLE_PROBE_THRESHOLD,
            "successful probes",
            ThresholdDirection.UNAVAILABLE,
            "Check the read-only storage probe mount; disk capacity is unknown.",
        ),
        AlertDefinition(
            AlertCode.WORKER_UNAVAILABLE,
            PRESENCE_TTL_SECONDS,
            "process presence TTL seconds; no valid presence",
            ThresholdDirection.UNAVAILABLE,
            "Check worker process logs and restart the matching release; old runs require explicit relaunch.",
        ),
        AlertDefinition(
            AlertCode.QUEUE_DELAY,
            QUEUE_AGE_ALERT_SECONDS,
            "seconds",
            ThresholdDirection.AT_LEAST,
            "Inspect worker presence and queue age; stop admission if progress cannot recover.",
        ),
        AlertDefinition(
            AlertCode.QUEUE_CAPACITY,
            PAPER_BETA.global_queued_runs,
            "queued runs",
            ThresholdDirection.AT_LEAST,
            "Inspect allowances and worker throughput before reopening admissions.",
        ),
        AlertDefinition(
            AlertCode.STUCK_RUN,
            DEFAULT_LEASE_SECONDS,
            "configured lease seconds; also missing heartbeat",
            ThresholdDirection.UNAVAILABLE,
            "Check recovery process; stop affected run or stop-all and verify terminal history.",
        ),
        AlertDefinition(
            AlertCode.STORAGE_GROWTH,
            DATABASE_SIZE_ALERT_BYTES,
            "bytes",
            ThresholdDirection.AT_LEAST,
            "Inspect database growth and lifecycle cleanup; stop admission before storage exhaustion.",
        ),
        AlertDefinition(
            AlertCode.STORAGE_LOW,
            DISK_FREE_ALERT_BYTES,
            "free bytes",
            ThresholdDirection.AT_MOST,
            "Stop admission; restore storage headroom without deleting retained database rows manually.",
        ),
        AlertDefinition(
            AlertCode.FEED_UNAVAILABLE,
            FEED_TTL_SECONDS,
            "seconds since observation; also missing or invalid input",
            ThresholdDirection.UNAVAILABLE,
            "Inspect worker/feed observations; use stop-run if input remains unavailable.",
        ),
        AlertDefinition(
            AlertCode.FEED_DEGRADED,
            FEED_LAG_ALERT_MS,
            "dispatch lag ms; also stale book",
            ThresholdDirection.AT_LEAST,
            "Inspect stale-book and dispatch-lag signals; stop affected runs until input recovers.",
        ),
        AlertDefinition(
            AlertCode.API_ERRORS,
            HTTP_ERROR_ALERT_COUNT,
            "responses in current plus previous minute",
            ThresholdDirection.AT_LEAST,
            "Inspect API and dependency health; use incident stop for sustained failures.",
        ),
        AlertDefinition(
            AlertCode.ADMISSION_REJECTIONS,
            ADMISSION_ALERT_COUNT,
            "responses in current plus previous minute",
            ThresholdDirection.AT_LEAST,
            "Check account/global allowances and queue capacity; do not bypass configured limits.",
        ),
    )
}
