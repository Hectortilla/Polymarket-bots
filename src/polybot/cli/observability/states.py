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
