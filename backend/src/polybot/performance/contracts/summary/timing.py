"""Timing section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..files import PerformanceTimingField
from ..parsing import nonnegative_int, require_exact_keys


@dataclass(frozen=True, slots=True)
class PerformanceTimingSummary:
    """Validated wall-clock and virtual duration for one performance run."""

    started_at_ms: int
    ended_at_ms: int
    virtual_duration_ms: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformanceTimingSummary:
        """Decode timing and require an exact virtual duration."""
        require_exact_keys(payload, PerformanceTimingField, "timing")
        started_at_ms = nonnegative_int(payload, PerformanceTimingField.STARTED_AT_MS)
        ended_at_ms = nonnegative_int(payload, PerformanceTimingField.ENDED_AT_MS)
        virtual_duration_ms = nonnegative_int(
            payload,
            PerformanceTimingField.VIRTUAL_DURATION_MS,
        )
        if (
            ended_at_ms < started_at_ms
            or virtual_duration_ms != ended_at_ms - started_at_ms
        ):
            raise ValueError("performance summary timing is inconsistent")
        return cls(started_at_ms, ended_at_ms, virtual_duration_ms)

    def to_dict(self) -> dict[str, int]:
        """Encode the stable timing section."""
        return {
            PerformanceTimingField.STARTED_AT_MS: self.started_at_ms,
            PerformanceTimingField.ENDED_AT_MS: self.ended_at_ms,
            PerformanceTimingField.VIRTUAL_DURATION_MS: self.virtual_duration_ms,
        }
