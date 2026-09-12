"""Replay coverage-gap policy shared by options and performance contracts."""

from enum import StrEnum


class BacktestGapPolicy(StrEnum):
    STRICT = "strict"
    BLACKOUT = "blackout"

    @property
    def allows_gaps(self) -> bool:
        """Whether replay may retain and explicitly blackout coverage gaps."""
        return self is BacktestGapPolicy.BLACKOUT
