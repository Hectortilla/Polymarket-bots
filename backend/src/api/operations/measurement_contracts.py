"""Operational measurement snapshots, projections and alert evaluation."""

from dataclasses import dataclass
from uuid import UUID

from api.operations.alerts import ALERT_DEFINITIONS
from api.operations.observations.contracts import (
    AlertCode,
    DatabaseObservation,
    RedisObservation,
)


@dataclass(frozen=True, slots=True)
class DatabaseMeasurements:
    queue_depth: int
    queue_age_seconds: float
    stuck_runs: int
    database_bytes: int
    active_run_ids: tuple[UUID, ...]
    admissions_paused: bool

    def observation(self) -> DatabaseObservation:
        return DatabaseObservation(
            self.queue_depth,
            self.queue_age_seconds,
            self.stuck_runs,
            self.database_bytes,
            self.admissions_paused,
        )

    def alerts(self) -> list[AlertCode]:
        alerts = []
        for code, value in (
            (AlertCode.QUEUE_CAPACITY, self.queue_depth),
            (AlertCode.QUEUE_DELAY, self.queue_age_seconds),
            (AlertCode.STORAGE_GROWTH, self.database_bytes),
        ):
            if ALERT_DEFINITIONS[code].breached(value):
                alerts.append(code)
        if self.stuck_runs:
            alerts.append(AlertCode.STUCK_RUN)
        return alerts


@dataclass(frozen=True, slots=True)
class RedisMeasurements:
    live_worker_count: int
    recent_http_error_count: int
    recent_admission_rejection_count: int

    def observation(self) -> RedisObservation:
        return RedisObservation(
            self.live_worker_count,
            self.recent_http_error_count,
            self.recent_admission_rejection_count,
        )

    def alerts(self) -> list[AlertCode]:
        alerts = []
        if self.live_worker_count == 0:
            alerts.append(AlertCode.WORKER_UNAVAILABLE)
        for code, value in (
            (AlertCode.API_ERRORS, self.recent_http_error_count),
            (AlertCode.ADMISSION_REJECTIONS, self.recent_admission_rejection_count),
        ):
            if ALERT_DEFINITIONS[code].breached(value):
                alerts.append(code)
        return alerts
