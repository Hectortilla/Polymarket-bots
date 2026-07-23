"""Durable JSON-summary serialization for performance result artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.performance.contracts.files import (
    EQUITY_FILE_NAME,
    ORDERS_FILE_NAME,
    RESULT_SCHEMA_VERSION,
    PerformanceArtifactField,
    PerformanceMetricsField,
    PerformancePositionField,
    PerformanceProvenanceField,
    PerformanceSelectionField,
    PerformanceSummaryField,
    PerformanceTimingField,
    PerformanceValuationField,
)
from polybot.performance.contracts.run import (
    PerformanceCounters,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
)
from polybot.performance.contracts.summary import PerformanceSummaryV1
from polybot.performance.metrics import EquityCurveMetrics
from polybot.performance.provenance import sanitized_configuration
from polybot.performance.valuation import (
    PortfolioValuation,
)

from .serialization import decimal_text, optional_decimal_text


@dataclass(frozen=True, slots=True)
class PerformanceSummaryInput:
    """All finalized run state needed to serialize one validated summary."""

    status: PerformanceRunStatus
    ended_at_ms: int
    error: str | None
    provenance: RunProvenance
    selection: RunSelection
    initial_cash_usdc: Decimal
    started_at_ms: int
    initial_valuation: PortfolioValuation
    final_valuation: PortfolioValuation
    final_fees_usdc: Decimal
    curve: EquityCurveMetrics
    counters: PerformanceCounters
    order_count: int
    fill_count: int
    rejected_count: int
    coverage_gap_rejected_order_count: int
    filled_notional_usdc: Decimal
    coverage_gap_affected_position_token_ids: tuple[str, ...]


def serialize_performance_summary(
    summary_input: PerformanceSummaryInput,
) -> dict[str, object]:
    """Build and schema-validate the final performance JSON payload."""
    net_pnl = summary_input.final_valuation.pnl_usdc
    gross_pnl = (
        None if net_pnl is None else net_pnl + summary_input.final_fees_usdc
    )
    return_fraction = (
        None if net_pnl is None else net_pnl / summary_input.initial_cash_usdc
    )
    raw_summary = {
        PerformanceSummaryField.SCHEMA_VERSION: RESULT_SCHEMA_VERSION,
        PerformanceSummaryField.STATUS: summary_input.status.value,
        PerformanceSummaryField.PARTIAL: summary_input.status.is_partial,
        PerformanceSummaryField.ERROR: summary_input.error,
        PerformanceSummaryField.PROVENANCE: _provenance_json(summary_input.provenance),
        PerformanceSummaryField.SELECTION: _selection_json(
            summary_input.selection,
            summary_input.coverage_gap_affected_position_token_ids,
        ),
        PerformanceSummaryField.TIMING: {
            PerformanceTimingField.STARTED_AT_MS: summary_input.started_at_ms,
            PerformanceTimingField.ENDED_AT_MS: summary_input.ended_at_ms,
            PerformanceTimingField.VIRTUAL_DURATION_MS: (
                summary_input.ended_at_ms - summary_input.started_at_ms
            ),
        },
        PerformanceSummaryField.METRICS: _metrics_json(
            summary_input,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            return_fraction=return_fraction,
        ),
        PerformanceSummaryField.VALUATION: _valuation_json(summary_input),
        PerformanceSummaryField.OPEN_POSITIONS: [
            {
                PerformancePositionField.TOKEN_ID: position.token_id,
                PerformancePositionField.SIZE: decimal_text(position.size),
                PerformancePositionField.AVERAGE_ENTRY_PRICE: optional_decimal_text(
                    position.average_entry_price
                ),
                PerformancePositionField.EXECUTABLE_MARK: optional_decimal_text(
                    position.executable_mark
                ),
                PerformancePositionField.LAST_EXECUTABLE_MARK: optional_decimal_text(
                    position.last_executable_mark
                ),
                PerformancePositionField.MARKET_VALUE_USDC: optional_decimal_text(
                    position.market_value_usdc
                ),
                PerformancePositionField.VALUATION_STATUS: position.status.value,
            }
            for position in summary_input.final_valuation.positions
        ],
        PerformanceSummaryField.ARTIFACTS: {
            PerformanceArtifactField.EQUITY: EQUITY_FILE_NAME,
            PerformanceArtifactField.ORDERS: ORDERS_FILE_NAME,
        },
    }
    return PerformanceSummaryV1.from_dict(raw_summary).to_dict()


def _provenance_json(provenance: RunProvenance) -> dict[str, object]:
    return {
        PerformanceProvenanceField.KIND: provenance.kind.value,
        PerformanceProvenanceField.BOT_SPEC: provenance.bot_spec,
        PerformanceProvenanceField.CONFIGURATION: sanitized_configuration(
            provenance.configuration
        ),
        PerformanceProvenanceField.SEED: provenance.seed,
        PerformanceProvenanceField.ARCHIVE_SHA256: provenance.archive_sha256,
        PerformanceProvenanceField.ARCHIVE_SCHEMA_VERSION: (
            provenance.archive_schema_version
        ),
        PerformanceProvenanceField.ARCHIVE_TARGET_IDENTITY: (
            provenance.archive_target_identity
        ),
    }


def _selection_json(
    selection: RunSelection,
    affected_position_token_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        PerformanceSelectionField.SESSION_ID: selection.session_id,
        PerformanceSelectionField.START_MS: selection.start_ms,
        PerformanceSelectionField.END_MS: selection.end_ms,
        PerformanceSelectionField.MARKET_SLUGS: list(selection.market_slugs),
        PerformanceSelectionField.REPLAY_CUTOFF_SEQUENCE: (
            selection.replay_cutoff_sequence
        ),
        PerformanceSelectionField.SESSION_INTEGRITY_STATUS: (
            None
            if selection.session_integrity_status is None
            else selection.session_integrity_status.value
        ),
        PerformanceSelectionField.USES_PARTIAL_SESSION: selection.uses_partial_session,
        PerformanceSelectionField.GAP_POLICY: (
            None if selection.gap_policy is None else selection.gap_policy.value
        ),
        PerformanceSelectionField.COVERAGE_GAP_IDS: list(selection.coverage_gap_ids),
        PerformanceSelectionField.COVERAGE_GAP_COUNT: len(selection.coverage_gap_ids),
        PerformanceSelectionField.COVERAGE_GAP_DURATION_MS: (
            selection.coverage_gap_duration_ms
        ),
        PerformanceSelectionField.COVERAGE_GAP_OPEN_COUNT: (
            selection.coverage_gap_open_count
        ),
        PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS: list(
            affected_position_token_ids
        ),
        PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_COUNT: len(
            affected_position_token_ids
        ),
    }


def _metrics_json(
    summary_input: PerformanceSummaryInput,
    *,
    gross_pnl: Decimal | None,
    net_pnl: Decimal | None,
    return_fraction: Decimal | None,
) -> dict[str, object]:
    return {
        PerformanceMetricsField.INITIAL_CASH_USDC: decimal_text(
            summary_input.initial_cash_usdc
        ),
        PerformanceMetricsField.INITIAL_EQUITY_USDC: optional_decimal_text(
            summary_input.initial_valuation.equity_usdc
        ),
        PerformanceMetricsField.FINAL_CASH_USDC: decimal_text(
            summary_input.final_valuation.cash_usdc
        ),
        PerformanceMetricsField.FINAL_MARKED_POSITION_VALUE_USDC: (
            optional_decimal_text(
                summary_input.final_valuation.marked_position_value_usdc
            )
        ),
        PerformanceMetricsField.FINAL_EQUITY_USDC: optional_decimal_text(
            summary_input.final_valuation.equity_usdc
        ),
        PerformanceMetricsField.GROSS_PNL_USDC: optional_decimal_text(gross_pnl),
        PerformanceMetricsField.NET_PNL_USDC: optional_decimal_text(net_pnl),
        PerformanceMetricsField.RETURN_FRACTION: optional_decimal_text(return_fraction),
        PerformanceMetricsField.FEES_USDC: decimal_text(summary_input.final_fees_usdc),
        PerformanceMetricsField.FILLED_NOTIONAL_USDC: decimal_text(
            summary_input.filled_notional_usdc
        ),
        PerformanceMetricsField.MAX_DRAWDOWN_USDC: optional_decimal_text(
            summary_input.curve.max_drawdown_usdc
        ),
        PerformanceMetricsField.MAX_DRAWDOWN_FRACTION: optional_decimal_text(
            summary_input.curve.max_drawdown_fraction
        ),
        PerformanceMetricsField.ORDER_COUNT: summary_input.order_count,
        PerformanceMetricsField.FILL_COUNT: summary_input.fill_count,
        PerformanceMetricsField.REJECTED_ORDER_COUNT: summary_input.rejected_count,
        PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT: (
            summary_input.coverage_gap_rejected_order_count
        ),
        PerformanceMetricsField.RESOLUTION_COUNT: (
            summary_input.counters.resolution_count
        ),
        PerformanceMetricsField.EVENT_COUNT: summary_input.counters.event_count,
        PerformanceMetricsField.DISPATCH_COUNT: summary_input.counters.dispatch_count,
        PerformanceMetricsField.ACCEPTED_DISPATCH_COUNT: (
            summary_input.counters.accepted_dispatch_count
        ),
        PerformanceMetricsField.SKIPPED_DISPATCH_COUNT: (
            summary_input.counters.skipped_dispatch_count
        ),
    }


def _valuation_json(
    summary_input: PerformanceSummaryInput,
) -> dict[str, object]:
    curve = summary_input.curve
    return {
        PerformanceValuationField.FINAL_STATUS: (
            summary_input.final_valuation.status.value
        ),
        PerformanceValuationField.HISTORY_STATUS: curve.history_status.value,
        PerformanceValuationField.DRAWDOWN_STATUS: curve.drawdown_status.value,
        PerformanceValuationField.COMPLETE: (
            curve.history_status.is_complete
        ),
        PerformanceValuationField.ESTIMATED: curve.stale_sample_count > 0,
        PerformanceValuationField.SAMPLE_COUNT: curve.sample_count,
        PerformanceValuationField.AVAILABLE_SAMPLE_COUNT: curve.available_sample_count,
        PerformanceValuationField.STALE_SAMPLE_COUNT: curve.stale_sample_count,
        PerformanceValuationField.UNAVAILABLE_SAMPLE_COUNT: (
            curve.unavailable_sample_count
        ),
    }
