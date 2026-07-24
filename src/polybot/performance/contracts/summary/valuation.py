"""Valuation-quality section of a persisted performance summary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot.performance.contracts.valuation_status import history_valuation_status

from ..files import PerformanceValuationField
from ..parsing import nonnegative_int, required_bool, required_text, require_exact_keys


@dataclass(frozen=True, slots=True)
class PerformanceValuationSummary:
    """Validated completeness and quality counters for equity valuation."""

    final_status: ValuationStatus
    history_status: ValuationStatus
    drawdown_status: ValuationStatus
    complete: bool
    estimated: bool
    sample_count: int
    available_sample_count: int
    stale_sample_count: int
    unavailable_sample_count: int

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> PerformanceValuationSummary:
        """Decode and cross-check the persisted valuation aggregates."""
        require_exact_keys(payload, PerformanceValuationField, "valuation")
        final_status = ValuationStatus(
            required_text(payload, PerformanceValuationField.FINAL_STATUS)
        )
        history_status = ValuationStatus(
            required_text(payload, PerformanceValuationField.HISTORY_STATUS)
        )
        drawdown_status = ValuationStatus(
            required_text(payload, PerformanceValuationField.DRAWDOWN_STATUS)
        )
        complete = required_bool(payload, PerformanceValuationField.COMPLETE)
        estimated = required_bool(payload, PerformanceValuationField.ESTIMATED)
        if complete is not history_status.is_complete:
            raise ValueError(
                "performance summary valuation completeness is inconsistent"
            )
        stale_sample_count = nonnegative_int(
            payload,
            PerformanceValuationField.STALE_SAMPLE_COUNT,
        )
        unavailable_sample_count = nonnegative_int(
            payload,
            PerformanceValuationField.UNAVAILABLE_SAMPLE_COUNT,
        )
        available_sample_count = nonnegative_int(
            payload,
            PerformanceValuationField.AVAILABLE_SAMPLE_COUNT,
        )
        sample_count = nonnegative_int(
            payload,
            PerformanceValuationField.SAMPLE_COUNT,
        )
        if estimated is not (stale_sample_count > 0):
            raise ValueError("performance summary valuation estimate is inconsistent")
        if available_sample_count + unavailable_sample_count != sample_count:
            raise ValueError(
                "performance summary valuation sample counts are inconsistent"
            )
        if stale_sample_count > available_sample_count:
            raise ValueError(
                "performance summary stale samples exceed available samples"
            )
        expected_history_status = history_valuation_status(
            stale_sample_count=stale_sample_count,
            unavailable_sample_count=unavailable_sample_count,
        )
        if history_status is not expected_history_status:
            raise ValueError(
                "performance summary valuation history status is inconsistent"
            )
        if drawdown_status is not history_status:
            raise ValueError(
                "performance summary valuation drawdown status is inconsistent"
            )
        return cls(
            final_status=final_status,
            history_status=history_status,
            drawdown_status=drawdown_status,
            complete=complete,
            estimated=estimated,
            sample_count=sample_count,
            available_sample_count=available_sample_count,
            stale_sample_count=stale_sample_count,
            unavailable_sample_count=unavailable_sample_count,
        )

    def to_dict(self) -> dict[str, object]:
        """Encode the stable valuation section."""
        return {
            PerformanceValuationField.FINAL_STATUS: self.final_status.value,
            PerformanceValuationField.HISTORY_STATUS: self.history_status.value,
            PerformanceValuationField.DRAWDOWN_STATUS: self.drawdown_status.value,
            PerformanceValuationField.COMPLETE: self.complete,
            PerformanceValuationField.ESTIMATED: self.estimated,
            PerformanceValuationField.SAMPLE_COUNT: self.sample_count,
            PerformanceValuationField.AVAILABLE_SAMPLE_COUNT: (
                self.available_sample_count
            ),
            PerformanceValuationField.STALE_SAMPLE_COUNT: self.stale_sample_count,
            PerformanceValuationField.UNAVAILABLE_SAMPLE_COUNT: (
                self.unavailable_sample_count
            ),
        }
