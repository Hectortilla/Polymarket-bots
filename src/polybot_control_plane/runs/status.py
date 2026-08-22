"""Dependency-light run lifecycle states."""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    def previous_statuses(self) -> frozenset["RunStatus"]:
        return frozenset(
            previous
            for previous, next_statuses in RUN_STATUS_TRANSITIONS.items()
            if self in next_statuses
        )


RUN_STATUS_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset(
        {RunStatus.STARTING, RunStatus.STOPPED, RunStatus.FAILED}
    ),
    RunStatus.STARTING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.STOP_REQUESTED,
            RunStatus.FAILED,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.STOP_REQUESTED,
            RunStatus.STOPPING,
            RunStatus.FAILED,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.STOP_REQUESTED: frozenset(
        {RunStatus.STOPPING, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.STOPPING: frozenset(
        {RunStatus.STOPPED, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.STOPPED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.INTERRUPTED: frozenset(),
}
TERMINAL_RUN_STATUSES = frozenset(
    status
    for status, next_statuses in RUN_STATUS_TRANSITIONS.items()
    if not next_statuses
)
QUEUED_PREVIOUS_STATUSES = frozenset({RunStatus.QUEUED})
OWNED_STOP_PREVIOUS_STATUSES = frozenset(
    {RunStatus.STARTING, RunStatus.RUNNING}
)
INTERRUPTIBLE_RUN_STATUSES = frozenset(
    {
        RunStatus.STARTING,
        RunStatus.RUNNING,
        RunStatus.STOP_REQUESTED,
        RunStatus.STOPPING,
    }
)
