"""Incremental, exact performance artifacts for paper and backtest runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path

from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
)
from polybot.framework.events.books import BookSnapshot
from polybot.persistence.atomic_json import AtomicJsonFile

from polybot.performance.contracts.files import (
    OrderField,
    SUMMARY_FILE_NAME,
)
from polybot.performance.contracts.sampling import DEFAULT_REPORT_INTERVAL_MS
from polybot.performance.contracts.run import (
    PerformanceCounters,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
    SampleReason,
)
from polybot.performance.contracts.valuation import (
    PortfolioLike,
    PortfolioValuation,
)

from .csv_output import PerformanceCsvOutput
from .errors import PerformanceArtifactStateError
from .sampling import PerformanceValuationSampler
from .serialization import (
    ZERO_USDC_AMOUNT,
    decimal_text,
    optional_decimal_text,
    validate_money,
)
from .summary import PerformanceSummaryInput, serialize_performance_summary




class PerformanceArtifacts:
    """Stream result rows and finalize one atomic summary.

    Call ``advance_to`` before applying an event at a later timestamp so any
    intervening interval samples reflect the state that actually preceded that
    event. Fill and settlement samples can then be appended at the same
    timestamp with ``record_transaction``.
    """

    def __init__(
        self,
        results_dir: str | Path,
        *,
        provenance: RunProvenance,
        selection: RunSelection,
        initial_cash_usdc: Decimal,
        report_interval_ms: int = DEFAULT_REPORT_INTERVAL_MS,
        max_book_age_ms: int | None = None,
    ) -> None:
        validate_money(initial_cash_usdc, "initial cash", positive=True)
        if (
            isinstance(report_interval_ms, bool)
            or not isinstance(report_interval_ms, int)
            or report_interval_ms <= 0
        ):
            raise ValueError("performance report interval must be positive")
        if max_book_age_ms is not None and (
            isinstance(max_book_age_ms, bool)
            or not isinstance(max_book_age_ms, int)
            or max_book_age_ms < 0
        ):
            raise ValueError("performance book maximum age must be nonnegative")
        self.results_dir = Path(results_dir)
        self.provenance = provenance
        self.selection = selection
        self.initial_cash_usdc = initial_cash_usdc
        self.report_interval_ms = report_interval_ms
        self.max_book_age_ms = max_book_age_ms
        self.counters = PerformanceCounters()
        self._sampler = PerformanceValuationSampler(
            initial_cash_usdc=initial_cash_usdc,
            max_book_age_ms=max_book_age_ms,
        )
        self._initial_valuation: PortfolioValuation | None = None
        self._next_interval_ms: int | None = None
        self._started_at_ms: int | None = None
        self._order_count = 0
        self._fill_count = 0
        self._recorded_fill_order_ids: set[str] = set()
        self._rejected_count = 0
        self._coverage_gap_rejected_order_count = 0
        self._coverage_gap_affected_position_token_ids: set[str] = set()
        self._filled_notional_usdc = ZERO_USDC_AMOUNT
        self._finalized = False
        self._output = PerformanceCsvOutput(self.results_dir)

    @property
    def books(self) -> Mapping[str, BookSnapshot]:
        return self._sampler.books

    @property
    def last_executable_marks(self) -> Mapping[str, Decimal]:
        return self._sampler.last_executable_marks

    @property
    def started(self) -> bool:
        return self._started_at_ms is not None

    @property
    def finalized(self) -> bool:
        return self._finalized

    def record_book(self, book: BookSnapshot) -> None:
        self._require_open()
        self._sampler.record_book(book)

    def remove_books(self, token_ids: tuple[str, ...]) -> None:
        self._require_open()
        self._sampler.remove_books(token_ids)

    def record_coverage_gap_affected_positions(
        self,
        token_ids: Iterable[str],
    ) -> None:
        self._require_open()
        normalized_token_ids: set[str] = set()
        for token_id in token_ids:
            if not isinstance(token_id, str) or not token_id.strip():
                raise ValueError(
                    "performance coverage-gap position token IDs must be text"
                )
            normalized_token_ids.add(token_id.strip())
        self._coverage_gap_affected_position_token_ids.update(
            normalized_token_ids
        )

    def record_events(self, count: int = 1) -> None:
        self._require_open()
        self.counters.record_events(count)

    def record_dispatch(self, accepted: bool | None) -> None:
        self._require_open()
        self.counters.record_dispatch(accepted)

    def start(self, timestamp_ms: int, portfolio: PortfolioLike) -> PortfolioValuation:
        self._require_open()
        if self.started:
            raise PerformanceArtifactStateError("performance run is already started")
        self._validate_timestamp(timestamp_ms)
        valuation = self._write_equity_sample(timestamp_ms, SampleReason.START, portfolio)
        self._started_at_ms = timestamp_ms
        self._next_interval_ms = timestamp_ms + self.report_interval_ms
        self._initial_valuation = valuation
        return valuation

    def advance_to(
        self,
        timestamp_ms: int,
        portfolio: PortfolioLike,
    ) -> PortfolioValuation | None:
        """Write every interval due through ``timestamp_ms`` using current state."""
        self._require_started()
        self._validate_timestamp(timestamp_ms)
        final_valuation: PortfolioValuation | None = None
        if self._next_interval_ms is None:
            raise AssertionError("started performance run requires next interval")
        while self._next_interval_ms <= timestamp_ms:
            final_valuation = self._write_equity_sample(
                self._next_interval_ms,
                SampleReason.INTERVAL,
                portfolio,
                flush=False,
            )
            self._next_interval_ms += self.report_interval_ms
        if final_valuation is not None:
            self._output.flush_equity()
        return final_valuation

    def record_transaction(
        self,
        timestamp_ms: int,
        reason: SampleReason,
        portfolio: PortfolioLike,
    ) -> PortfolioValuation:
        if reason not in {SampleReason.FILL, SampleReason.SETTLEMENT}:
            raise ValueError("performance transaction reason must be fill or settlement")
        self.advance_to(timestamp_ms, portfolio)
        return self._write_equity_sample(timestamp_ms, reason, portfolio)

    def record_sample(
        self,
        timestamp_ms: int,
        portfolio: PortfolioLike,
    ) -> PortfolioValuation:
        self.advance_to(timestamp_ms, portfolio)
        return self._write_equity_sample(timestamp_ms, SampleReason.MANUAL, portfolio)

    def record_order_result(
        self,
        *,
        submitted_at_ms: int,
        order: OrderRequest,
        fill: FillEvent,
    ) -> bool:
        self._require_started()
        self._validate_timestamp(submitted_at_ms)
        self._validate_timestamp(fill.received_at_ms)
        if fill.received_at_ms < submitted_at_ms:
            raise ValueError("order completion must not precede submission")
        self._output.write_order(
            {
                OrderField.SUBMITTED_AT_MS: submitted_at_ms,
                OrderField.COMPLETED_AT_MS: fill.received_at_ms,
                OrderField.ORDER_ID: fill.order_id,
                OrderField.MARKET_SLUG: order.market_slug,
                OrderField.CONDITION_ID: order.condition_id,
                OrderField.TOKEN_ID: order.token_id,
                OrderField.SIDE: order.side.value,
                OrderField.REQUESTED_PRICE: decimal_text(order.price),
                OrderField.REQUESTED_SIZE: decimal_text(order.size),
                OrderField.STATUS: fill.status.value,
                OrderField.FILLED_SIZE: decimal_text(fill.filled_size),
                OrderField.AVERAGE_PRICE: optional_decimal_text(fill.average_price),
                OrderField.FEE_USDC: decimal_text(fill.fee_usdc),
                OrderField.REJECT_REASON: (
                    None if fill.reject_reason is None else fill.reject_reason.value
                ),
                OrderField.REJECT_MESSAGE: fill.reject_message,
                OrderField.STRATEGY_REASON: order.reason,
                OrderField.SOURCE_ID: order.source_id,
            }
        )
        self._order_count += 1
        if fill.status is OrderStatus.REJECTED:
            self._rejected_count += 1
        if fill.reject_reason is FillRejectReason.BACKTEST_COVERAGE_GAP:
            self._coverage_gap_rejected_order_count += 1
        is_new_fill = (
            fill.has_execution
            and fill.order_id not in self._recorded_fill_order_ids
        )
        if is_new_fill:
            self._recorded_fill_order_ids.add(fill.order_id)
            self._fill_count += 1
            self._filled_notional_usdc += fill.filled_size * fill.execution_price
        return is_new_fill

    def record_fill(
        self,
        *,
        submitted_at_ms: int,
        order: OrderRequest,
        fill: FillEvent,
        portfolio: PortfolioLike,
    ) -> PortfolioValuation | None:
        """Record an order outcome and sample successful portfolio changes."""
        is_new_fill = self.record_order_result(
            submitted_at_ms=submitted_at_ms,
            order=order,
            fill=fill,
        )
        if not is_new_fill:
            return None
        return self.record_transaction(fill.received_at_ms, SampleReason.FILL, portfolio)

    def record_settlement(
        self,
        *,
        timestamp_ms: int,
        portfolio: PortfolioLike,
    ) -> PortfolioValuation:
        valuation = self.record_transaction(
            timestamp_ms,
            SampleReason.SETTLEMENT,
            portfolio,
        )
        self.counters.record_resolutions()
        return valuation

    def finalize(
        self,
        *,
        status: PerformanceRunStatus,
        ended_at_ms: int,
        portfolio: PortfolioLike,
        error: str | None = None,
    ) -> dict[str, object]:
        self._require_started()
        if not isinstance(status, PerformanceRunStatus):
            raise ValueError("performance run status is invalid")
        status.validate_error(error)
        self.advance_to(ended_at_ms, portfolio)
        final_valuation = self._write_equity_sample(
            ended_at_ms,
            SampleReason.END,
            portfolio,
        )
        summary = self._summary(
            status=status,
            ended_at_ms=ended_at_ms,
            final_valuation=final_valuation,
            final_fees_usdc=portfolio.cumulative_fees_usdc,
            error=error,
        )
        self._output.close()
        AtomicJsonFile(self.results_dir / SUMMARY_FILE_NAME).write(summary)
        self._finalized = True
        return summary

    def _write_equity_sample(
        self,
        timestamp_ms: int,
        reason: SampleReason,
        portfolio: PortfolioLike,
        *,
        flush: bool = True,
    ) -> PortfolioValuation:
        sample = self._sampler.sample(timestamp_ms, reason, portfolio)
        self._output.write_equity(sample.row, flush=flush)
        return sample.valuation

    def _summary(
        self,
        *,
        status: PerformanceRunStatus,
        ended_at_ms: int,
        final_valuation: PortfolioValuation,
        final_fees_usdc: Decimal,
        error: str | None,
    ) -> dict[str, object]:
        if self._started_at_ms is None or self._initial_valuation is None:
            raise AssertionError("started performance run requires initial valuation")
        return serialize_performance_summary(
            PerformanceSummaryInput(
                status=status,
                ended_at_ms=ended_at_ms,
                error=error,
                provenance=self.provenance,
                selection=self.selection,
                initial_cash_usdc=self.initial_cash_usdc,
                started_at_ms=self._started_at_ms,
                initial_valuation=self._initial_valuation,
                final_valuation=final_valuation,
                final_fees_usdc=final_fees_usdc,
                curve=self._sampler.curve,
                counters=self.counters,
                order_count=self._order_count,
                fill_count=self._fill_count,
                rejected_count=self._rejected_count,
                coverage_gap_rejected_order_count=(
                    self._coverage_gap_rejected_order_count
                ),
                filled_notional_usdc=self._filled_notional_usdc,
                coverage_gap_affected_position_token_ids=tuple(
                    sorted(self._coverage_gap_affected_position_token_ids)
                ),
            )
        )

    def _validate_timestamp(self, timestamp_ms: int) -> None:
        if (
            isinstance(timestamp_ms, bool)
            or not isinstance(timestamp_ms, int)
            or timestamp_ms < 0
        ):
            raise ValueError("performance timestamp must be nonnegative")
        if timestamp_ms < self.selection.start_ms:
            raise ValueError("performance timestamp precedes selected range")
        if self.selection.end_ms is not None and timestamp_ms > self.selection.end_ms:
            raise ValueError("performance timestamp exceeds selected range")

    def _require_open(self) -> None:
        if self._finalized:
            raise PerformanceArtifactStateError("performance run is finalized")

    def _require_started(self) -> None:
        self._require_open()
        if not self.started:
            raise PerformanceArtifactStateError("performance run is not started")
