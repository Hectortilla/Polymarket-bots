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
