"""Normalized Polymarket resolution lifecycle states."""

from __future__ import annotations

from enum import StrEnum


class ResolutionStatus(StrEnum):
    DISPUTED = "disputed"
    PROPOSED = "proposed"
    REQUESTED = "requested"
    RESOLVED = "resolved"
    SETTLED = "settled"

    @property
    def is_final(self) -> bool:
        return self in FINAL_RESOLUTION_STATUSES


FINAL_RESOLUTION_STATUSES = frozenset(
    (ResolutionStatus.RESOLVED, ResolutionStatus.SETTLED)
)
