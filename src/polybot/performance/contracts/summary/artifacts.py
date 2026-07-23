"""Artifact-file section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..files import PerformanceArtifactField
from ..parsing import required_text, require_exact_keys


@dataclass(frozen=True, slots=True)
class PerformanceArtifactSummary:
    """Validated names of the companion performance artifact files."""

    equity: str
    orders: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformanceArtifactSummary:
        """Decode the exact artifact-file object."""
        require_exact_keys(payload, PerformanceArtifactField, "artifacts")
        return cls(
            equity=required_text(payload, PerformanceArtifactField.EQUITY),
            orders=required_text(payload, PerformanceArtifactField.ORDERS),
        )

    def to_dict(self) -> dict[str, str]:
        """Encode the stable artifact-file section."""
        return {
            PerformanceArtifactField.EQUITY: self.equity,
            PerformanceArtifactField.ORDERS: self.orders,
        }
