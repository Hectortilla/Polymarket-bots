"""Versioned performance-summary envelope and section validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from polybot.persistence.json_codec import loads_json

from ..files import RESULT_SCHEMA_VERSION, PerformanceSummaryField
from ..parsing import (
    required_bool,
    required_mapping,
    required_text,
    require_exact_keys,
)
from ..run import PerformanceRunStatus
from . import artifacts as artifact_section
from . import metrics as metrics_section
from . import positions as positions_section
from . import provenance as provenance_section
from . import selection as selection_section
from . import timing as timing_section
from . import valuation as valuation_section


@dataclass(frozen=True, slots=True)
class PerformanceSummaryV1:
    """The root schema envelope for one persisted performance result."""

    status: PerformanceRunStatus
    partial: bool
    error: str | None
    provenance: provenance_section.PerformanceProvenanceSummary
    selection: selection_section.PerformanceSelectionSummary
    timing: timing_section.PerformanceTimingSummary
    metrics: metrics_section.PerformanceMetricsSummary
    valuation: valuation_section.PerformanceValuationSummary
    open_positions: tuple[positions_section.PerformancePositionSummary, ...]
    artifacts: artifact_section.PerformanceArtifactSummary

    @classmethod
    def read(cls, path: str | Path) -> PerformanceSummaryV1:
        """Read and validate one JSON summary file."""
        payload = loads_json(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("performance summary must contain a JSON object")
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> PerformanceSummaryV1:
        """Decode the root envelope and delegate each semantic section."""
        require_exact_keys(payload, PerformanceSummaryField, "root")
        schema_version = payload.get(PerformanceSummaryField.SCHEMA_VERSION)
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != RESULT_SCHEMA_VERSION
        ):
            raise ValueError("unsupported performance summary schema version")
        status = PerformanceRunStatus(
            required_text(payload, PerformanceSummaryField.STATUS)
        )
        partial = required_bool(payload, PerformanceSummaryField.PARTIAL)
        if partial is not status.is_partial:
            raise ValueError("performance summary partial status is inconsistent")
        raw_error = payload.get(PerformanceSummaryField.ERROR)
        if raw_error is not None and not isinstance(raw_error, str):
            raise ValueError("performance summary error must be text or null")
        status.validate_error(raw_error)
        raw_open_positions = payload.get(PerformanceSummaryField.OPEN_POSITIONS)
        if not isinstance(raw_open_positions, list) or not all(
            isinstance(position, dict) for position in raw_open_positions
        ):
            raise ValueError("performance summary open positions are malformed")
        open_positions = tuple(
            positions_section.PerformancePositionSummary.from_dict(position)
            for position in raw_open_positions
        )
        if len({position.token_id for position in open_positions}) != len(
            open_positions
        ):
            raise ValueError(
                "performance summary open positions contain duplicate tokens"
            )
        return cls(
            status=status,
            partial=partial,
            error=raw_error,
            provenance=provenance_section.PerformanceProvenanceSummary.from_dict(
                required_mapping(payload, PerformanceSummaryField.PROVENANCE)
            ),
            selection=selection_section.PerformanceSelectionSummary.from_dict(
                required_mapping(payload, PerformanceSummaryField.SELECTION)
            ),
            timing=timing_section.PerformanceTimingSummary.from_dict(
                required_mapping(payload, PerformanceSummaryField.TIMING)
            ),
            metrics=metrics_section.PerformanceMetricsSummary.from_dict(
                required_mapping(payload, PerformanceSummaryField.METRICS)
            ),
            valuation=valuation_section.PerformanceValuationSummary.from_dict(
                required_mapping(payload, PerformanceSummaryField.VALUATION)
            ),
            open_positions=open_positions,
            artifacts=artifact_section.PerformanceArtifactSummary.from_dict(
                required_mapping(payload, PerformanceSummaryField.ARTIFACTS)
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Encode the stable root schema and all validated sections."""
        return {
            PerformanceSummaryField.SCHEMA_VERSION: RESULT_SCHEMA_VERSION,
            PerformanceSummaryField.STATUS: self.status.value,
            PerformanceSummaryField.PARTIAL: self.partial,
            PerformanceSummaryField.ERROR: self.error,
            PerformanceSummaryField.PROVENANCE: self.provenance.to_dict(),
            PerformanceSummaryField.SELECTION: self.selection.to_dict(),
            PerformanceSummaryField.TIMING: self.timing.to_dict(),
            PerformanceSummaryField.METRICS: self.metrics.to_dict(),
            PerformanceSummaryField.VALUATION: self.valuation.to_dict(),
            PerformanceSummaryField.OPEN_POSITIONS: [
                position.to_dict() for position in self.open_positions
            ],
            PerformanceSummaryField.ARTIFACTS: self.artifacts.to_dict(),
        }
