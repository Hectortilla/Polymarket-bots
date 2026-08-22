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


def validate_bootstrap_progress(completed: int, total: int) -> None:
    if completed < 0 or total < 0:
        raise ValueError("bootstrap progress values must not be negative")
    if completed > total:
        raise ValueError("bootstrap progress cannot exceed its total")
