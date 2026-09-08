"""Dependency-light lifecycle states shared by observers and projections."""

from enum import StrEnum


class RuntimeState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class BootstrapPhase(StrEnum):
    MARKETS = "markets"
    WALLETS = "wallets"


BOOTSTRAP_PROGRESS_MINIMUM = 0
BOOTSTRAP_COMPLETED_MAY_EXCEED_TOTAL = False


def validate_bootstrap_progress(completed: int, total: int) -> None:
    if completed < BOOTSTRAP_PROGRESS_MINIMUM or total < BOOTSTRAP_PROGRESS_MINIMUM:
        raise ValueError("bootstrap progress values must not be negative")
    if not BOOTSTRAP_COMPLETED_MAY_EXCEED_TOTAL and completed > total:
        raise ValueError("bootstrap progress cannot exceed its total")
