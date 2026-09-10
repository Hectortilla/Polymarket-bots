"""Payload-free typed records emitted only from internal operational facts."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class Observation(StrEnum):
    HTTP_ERROR = "http_error"
    ADMISSION_REJECTION = "admission_rejection"
    TELEMETRY_UNAVAILABLE = "telemetry_unavailable"
    SNAPSHOT = "snapshot"
    ALERT = "alert"
    OBSERVER_FAILURE = "observer_failure"
    LOG_OVERFLOW = "log_overflow"


class ProbeSource(StrEnum):
    DATABASE = "database"
    DISK = "disk"
    REDIS = "redis"


class AlertCode(StrEnum):
    DATABASE_UNAVAILABLE = "database_unavailable"
    CONTROL_UNAVAILABLE = "control_unavailable"
    REDIS_UNAVAILABLE = "redis_unavailable"
    TELEMETRY_INVALID = "telemetry_invalid"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    WORKER_UNAVAILABLE = "worker_unavailable"
    QUEUE_DELAY = "queue_delay"
    QUEUE_CAPACITY = "queue_capacity"
    STUCK_RUN = "stuck_run"
    STORAGE_GROWTH = "storage_growth"
    STORAGE_LOW = "storage_low"
    FEED_UNAVAILABLE = "feed_unavailable"
    FEED_DEGRADED = "feed_degraded"
    API_ERRORS = "api_errors"
    ADMISSION_REJECTIONS = "admission_rejections"


@dataclass(frozen=True, slots=True)
class HttpObservation:
    event: Literal[Observation.HTTP_ERROR, Observation.ADMISSION_REJECTION]
    status: int


@dataclass(frozen=True, slots=True)
class FailureObservation:
    event: Literal[Observation.TELEMETRY_UNAVAILABLE, Observation.OBSERVER_FAILURE]


@dataclass(frozen=True, slots=True)
class DatabaseObservation:
    queue_depth: int
    queue_age_seconds: float
    stuck_runs: int
    database_bytes: int
    admissions_paused: bool
    event: Literal[Observation.SNAPSHOT] = field(
        default=Observation.SNAPSHOT, init=False
    )
    source: Literal[ProbeSource.DATABASE] = field(
        default=ProbeSource.DATABASE, init=False
    )


@dataclass(frozen=True, slots=True)
class DiskObservation:
    disk_free_bytes: int
    event: Literal[Observation.SNAPSHOT] = field(
        default=Observation.SNAPSHOT, init=False
    )
    source: Literal[ProbeSource.DISK] = field(default=ProbeSource.DISK, init=False)


@dataclass(frozen=True, slots=True)
class RedisObservation:
    live_worker_count: int
    recent_http_error_count: int
    recent_admission_rejection_count: int
    event: Literal[Observation.SNAPSHOT] = field(
        default=Observation.SNAPSHOT, init=False
    )
    source: Literal[ProbeSource.REDIS] = field(default=ProbeSource.REDIS, init=False)


@dataclass(frozen=True, slots=True)
class AlertObservation:
    code: AlertCode
    owner: str
    threshold: float
    unit: str
    response: str
    event: Literal[Observation.ALERT] = field(default=Observation.ALERT, init=False)


@dataclass(frozen=True, slots=True)
class LogOverflowObservation:
    dropped_records: int
    event: Literal[Observation.LOG_OVERFLOW] = field(
        default=Observation.LOG_OVERFLOW, init=False
    )


type OperationalRecord = (
    HttpObservation
    | FailureObservation
    | DatabaseObservation
    | DiskObservation
    | RedisObservation
    | AlertObservation
    | LogOverflowObservation
)
