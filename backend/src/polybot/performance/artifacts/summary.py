"""Durable JSON-summary serialization for performance result artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.performance.contracts.files import (
    EQUITY_FILE_NAME,
    ORDERS_FILE_NAME,
)
from polybot.performance.contracts.run import (
    PerformanceCounters,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
)
from polybot.performance.contracts.summary import PerformanceSummaryV1
from polybot.performance.contracts.summary.artifacts import (
    PerformanceArtifactSummary,
)
from polybot.performance.contracts.summary.metrics import PerformanceMetricsSummary
from polybot.performance.contracts.summary.positions import (
    PerformancePositionSummary,
)
from polybot.performance.contracts.summary.provenance import (
    PerformanceProvenanceSummary,
)
from polybot.performance.contracts.summary.selection import (
    PerformanceSelectionSummary,
)
from polybot.performance.contracts.summary.timing import PerformanceTimingSummary
from polybot.performance.contracts.summary.valuation import (
    PerformanceValuationSummary,
)
from polybot.performance.contracts.valuation import PortfolioValuation
from polybot.performance.metrics import EquityCurveMetrics
from polybot.performance.provenance import sanitized_configuration

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

    def to_schema_dict(
        self,
    ) -> dict[str, object]:
        """Build and schema-validate the final performance JSON payload."""
        net_pnl = self.final_valuation.pnl_usdc
        gross_pnl = None if net_pnl is None else net_pnl + self.final_fees_usdc
        return_fraction = None if net_pnl is None else net_pnl / self.initial_cash_usdc
        selection = self.selection
        curve = self.curve
        summary = PerformanceSummaryV1(
            status=self.status,
            partial=self.status.is_partial,
            error=self.error,
            provenance=PerformanceProvenanceSummary(
                kind=self.provenance.kind,
                bot_spec=self.provenance.bot_spec,
                configuration=sanitized_configuration(self.provenance.configuration),
                seed=self.provenance.seed,
                archive_sha256=self.provenance.archive_sha256,
                archive_schema_version=(self.provenance.archive_schema_version),
                archive_target_identity=(self.provenance.archive_target_identity),
            ),
            selection=PerformanceSelectionSummary(
                session_id=selection.session_id,
                start_ms=selection.start_ms,
                end_ms=selection.end_ms,
                market_slugs=selection.market_slugs,
                replay_cutoff_sequence=selection.replay_cutoff_sequence,
                session_integrity_status=selection.session_integrity_status,
                uses_partial_session=selection.uses_partial_session,
                gap_policy=selection.gap_policy,
                coverage_gap_ids=selection.coverage_gap_ids,
                coverage_gap_duration_ms=selection.coverage_gap_duration_ms,
                coverage_gap_open_count=selection.coverage_gap_open_count,
                coverage_gap_affected_position_token_ids=(
                    self.coverage_gap_affected_position_token_ids
                ),
            ),
            timing=PerformanceTimingSummary(
                started_at_ms=self.started_at_ms,
                ended_at_ms=self.ended_at_ms,
                virtual_duration_ms=(self.ended_at_ms - self.started_at_ms),
            ),
            metrics=PerformanceMetricsSummary(
                initial_cash_usdc=decimal_text(self.initial_cash_usdc),
                initial_equity_usdc=optional_decimal_text(
                    self.initial_valuation.equity_usdc
                ),
                final_cash_usdc=decimal_text(self.final_valuation.cash_usdc),
                final_marked_position_value_usdc=optional_decimal_text(
                    self.final_valuation.marked_position_value_usdc
                ),
                final_equity_usdc=optional_decimal_text(
                    self.final_valuation.equity_usdc
                ),
                gross_pnl_usdc=optional_decimal_text(gross_pnl),
                net_pnl_usdc=optional_decimal_text(net_pnl),
                return_fraction=optional_decimal_text(return_fraction),
                fees_usdc=decimal_text(self.final_fees_usdc),
                filled_notional_usdc=decimal_text(self.filled_notional_usdc),
                max_drawdown_usdc=optional_decimal_text(curve.max_drawdown_usdc),
                max_drawdown_fraction=optional_decimal_text(
                    curve.max_drawdown_fraction
                ),
                order_count=self.order_count,
                fill_count=self.fill_count,
                rejected_order_count=self.rejected_count,
                coverage_gap_rejected_order_count=(
                    self.coverage_gap_rejected_order_count
                ),
                resolution_count=self.counters.resolution_count,
                event_count=self.counters.event_count,
                dispatch_count=self.counters.dispatch_count,
                accepted_dispatch_count=(self.counters.accepted_dispatch_count),
                skipped_dispatch_count=(self.counters.skipped_dispatch_count),
            ),
            valuation=PerformanceValuationSummary(
                final_status=self.final_valuation.status,
                history_status=curve.history_status,
                drawdown_status=curve.drawdown_status,
                complete=curve.history_status.is_complete,
                estimated=curve.stale_sample_count > 0,
                sample_count=curve.sample_count,
                available_sample_count=curve.available_sample_count,
                stale_sample_count=curve.stale_sample_count,
                unavailable_sample_count=curve.unavailable_sample_count,
            ),
            open_positions=tuple(
                PerformancePositionSummary(
                    token_id=position.token_id,
                    size=decimal_text(position.size),
                    average_entry_price=optional_decimal_text(
                        position.average_entry_price
                    ),
                    executable_mark=optional_decimal_text(position.executable_mark),
                    last_executable_mark=optional_decimal_text(
                        position.last_executable_mark
                    ),
                    market_value_usdc=optional_decimal_text(position.market_value_usdc),
                    valuation_status=position.status,
                )
                for position in self.final_valuation.positions
            ),
            artifacts=PerformanceArtifactSummary(
                equity=EQUITY_FILE_NAME,
                orders=ORDERS_FILE_NAME,
            ),
        )
        return summary.to_dict()
