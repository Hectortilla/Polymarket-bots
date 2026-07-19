"""Incremental, exact performance artifacts for paper and backtest runs."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import TextIO

from polybot.cli.persistence import AtomicJsonFile
from polybot.framework.events import FillEvent, OrderRequest, OrderStatus
from polybot.framework.events.books import BookSnapshot

from .contracts import (
    DEFAULT_REPORT_INTERVAL_MS,
    EQUITY_FIELDS,
    EQUITY_FILE_NAME,
    ORDERS_FILE_NAME,
    ORDER_FIELDS,
    RESULT_SCHEMA_VERSION,
    SUMMARY_FILE_NAME,
    PerformanceCounters,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
    SampleReason,
)
from .metrics import EquityCurveMetrics
from .provenance import sanitized_configuration
from .valuation import (
    PortfolioLike,
    PortfolioValuation,
    ValuationStatus,
    value_portfolio,
)


ZERO = Decimal("0")


class PerformanceArtifactError(RuntimeError):
    """Base error for result-artifact lifecycle failures."""


class PerformanceOutputExistsError(PerformanceArtifactError):
    pass


class PerformanceArtifactStateError(PerformanceArtifactError):
    pass


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
        _validate_money(initial_cash_usdc, "initial cash", positive=True)
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
        self._books: dict[str, BookSnapshot] = {}
        self._last_executable_marks: dict[str, Decimal] = {}
        self._curve = EquityCurveMetrics()
        self._initial_valuation: PortfolioValuation | None = None
        self._next_interval_ms: int | None = None
        self._started_at_ms: int | None = None
        self._order_count = 0
        self._fill_count = 0
        self._recorded_fill_order_ids: set[str] = set()
        self._rejected_count = 0
        self._filled_notional_usdc = ZERO
        self._finalized = False
        self._equity_file: TextIO | None = None
        self._orders_file: TextIO | None = None
        self._create_output()

    @property
    def books(self) -> Mapping[str, BookSnapshot]:
        return self._books

    @property
    def last_executable_marks(self) -> Mapping[str, Decimal]:
        return self._last_executable_marks

    @property
    def started(self) -> bool:
        return self._started_at_ms is not None

    @property
    def finalized(self) -> bool:
        return self._finalized

    def record_book(self, book: BookSnapshot) -> None:
        self._require_open()
        self._books[book.token_id] = book

    def remove_books(self, token_ids: tuple[str, ...]) -> None:
        self._require_open()
        for token_id in token_ids:
            self._books.pop(token_id, None)
            self._last_executable_marks.pop(token_id, None)

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
            self._flush_equity()
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
        if fill.filled_size > ZERO and fill.average_price is None:
            raise ValueError("a positive fill requires an average price")
        writer = self._required_orders_writer()
        writer.writerow(
            {
                "submitted_at_ms": submitted_at_ms,
                "completed_at_ms": fill.received_at_ms,
                "order_id": fill.order_id,
                "market_slug": order.market_slug,
                "condition_id": order.condition_id,
                "token_id": order.token_id,
                "side": order.side.value,
                "requested_price": _decimal_text(order.price),
                "requested_size": _decimal_text(order.size),
                "status": fill.status.value,
                "filled_size": _decimal_text(fill.filled_size),
                "average_price": _optional_decimal_text(fill.average_price),
                "fee_usdc": _decimal_text(fill.fee_usdc),
                "reject_reason": (
                    None if fill.reject_reason is None else fill.reject_reason.value
                ),
                "reject_message": fill.reject_message,
                "strategy_reason": order.reason,
                "source_id": order.source_id,
            }
        )
        self._flush_orders()
        self._order_count += 1
        if fill.status is OrderStatus.REJECTED:
            self._rejected_count += 1
        is_new_fill = (
            fill.filled_size > ZERO
            and fill.order_id not in self._recorded_fill_order_ids
        )
        if is_new_fill:
            if fill.average_price is None:
                raise AssertionError("validated positive fill requires average price")
            self._recorded_fill_order_ids.add(fill.order_id)
            self._fill_count += 1
            self._filled_notional_usdc += fill.filled_size * fill.average_price
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
        self._require_started()
        self._validate_timestamp(timestamp_ms)
        self.counters.record_resolutions()
        return self.record_transaction(
            timestamp_ms,
            SampleReason.SETTLEMENT,
            portfolio,
        )

    def finalize(
        self,
        *,
        status: PerformanceRunStatus,
        ended_at_ms: int,
        portfolio: PortfolioLike,
        error: str | None = None,
    ) -> dict[str, object]:
        self._require_started()
        self._validate_timestamp(ended_at_ms)
        if status is PerformanceRunStatus.FAILED and not (error and error.strip()):
            raise ValueError("failed performance runs require an error")
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
        self._close_csv_files()
        AtomicJsonFile(self.results_dir / SUMMARY_FILE_NAME).write(summary)
        self._finalized = True
        return summary

    def _create_output(self) -> None:
        try:
            self.results_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise PerformanceOutputExistsError(
                f"performance results directory already exists: {self.results_dir}"
            ) from error
        try:
            self._equity_file = (self.results_dir / EQUITY_FILE_NAME).open(
                "x",
                encoding="utf-8",
                newline="",
            )
            self._orders_file = (self.results_dir / ORDERS_FILE_NAME).open(
                "x",
                encoding="utf-8",
                newline="",
            )
            self._equity_writer = csv.DictWriter(
                self._equity_file,
                fieldnames=EQUITY_FIELDS,
            )
            self._orders_writer = csv.DictWriter(
                self._orders_file,
                fieldnames=ORDER_FIELDS,
            )
            self._equity_writer.writeheader()
            self._orders_writer.writeheader()
            self._flush_equity()
            self._flush_orders()
        except Exception:
            self._close_csv_files()
            raise

    def _write_equity_sample(
        self,
        timestamp_ms: int,
        reason: SampleReason,
        portfolio: PortfolioLike,
        *,
        flush: bool = True,
    ) -> PortfolioValuation:
        valuation = value_portfolio(
            portfolio,
            self._books,
            now_ms=timestamp_ms,
            max_book_age_ms=self.max_book_age_ms,
            initial_cash_usdc=self.initial_cash_usdc,
            last_executable_marks=self._last_executable_marks,
            allow_stale_marks=True,
        )
        self._curve.record(timestamp_ms, valuation)
        self._required_equity_writer().writerow(
            {
                "timestamp_ms": timestamp_ms,
                "sample_reason": reason.value,
                "cash_usdc": _decimal_text(valuation.cash_usdc),
                "marked_position_value_usdc": _optional_decimal_text(
                    valuation.marked_position_value_usdc
                ),
                "equity_usdc": _optional_decimal_text(valuation.equity_usdc),
                "pnl_usdc": _optional_decimal_text(valuation.pnl_usdc),
                "fees_usdc": _decimal_text(portfolio.cumulative_fees_usdc),
                "exposure_usdc": _optional_decimal_text(
                    valuation.exposure_usdc
                ),
                "position_count": valuation.position_count,
                "valuation_status": valuation.status.value,
            }
        )
        if flush:
            self._flush_equity()
        return valuation

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
        net_pnl = final_valuation.pnl_usdc
        gross_pnl = None if net_pnl is None else net_pnl + final_fees_usdc
        return_fraction = (
            None if net_pnl is None else net_pnl / self.initial_cash_usdc
        )
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": status.value,
            "partial": status is not PerformanceRunStatus.COMPLETED,
            "error": error,
            "provenance": self._provenance_json(),
            "selection": {
                "session_id": self.selection.session_id,
                "start_ms": self.selection.start_ms,
                "end_ms": self.selection.end_ms,
                "market_slugs": list(self.selection.market_slugs),
                "replay_cutoff_sequence": (
                    self.selection.replay_cutoff_sequence
                ),
                "session_integrity_status": (
                    self.selection.session_integrity_status
                ),
                "uses_partial_session": self.selection.uses_partial_session,
            },
            "timing": {
                "started_at_ms": self._started_at_ms,
                "ended_at_ms": ended_at_ms,
                "virtual_duration_ms": ended_at_ms - self._started_at_ms,
            },
            "metrics": {
                "initial_cash_usdc": _decimal_text(self.initial_cash_usdc),
                "initial_equity_usdc": _optional_decimal_text(
                    self._initial_valuation.equity_usdc
                ),
                "final_cash_usdc": _decimal_text(final_valuation.cash_usdc),
                "final_marked_position_value_usdc": _optional_decimal_text(
                    final_valuation.marked_position_value_usdc
                ),
                "final_equity_usdc": _optional_decimal_text(
                    final_valuation.equity_usdc
                ),
                "gross_pnl_usdc": _optional_decimal_text(gross_pnl),
                "net_pnl_usdc": _optional_decimal_text(net_pnl),
                "return": _optional_decimal_text(return_fraction),
                "fees_usdc": _decimal_text(final_fees_usdc),
                "filled_notional_usdc": _decimal_text(
                    self._filled_notional_usdc
                ),
                "max_drawdown_usdc": _optional_decimal_text(
                    self._curve.max_drawdown_usdc
                ),
                "max_drawdown_fraction": _optional_decimal_text(
                    self._curve.max_drawdown_fraction
                ),
                "order_count": self._order_count,
                "fill_count": self._fill_count,
                "rejected_order_count": self._rejected_count,
                "resolution_count": self.counters.resolution_count,
                "event_count": self.counters.event_count,
                "dispatch_count": self.counters.dispatch_count,
                "accepted_dispatch_count": self.counters.accepted_dispatch_count,
                "skipped_dispatch_count": self.counters.skipped_dispatch_count,
            },
            "valuation": {
                "final_status": final_valuation.status.value,
                "history_status": self._curve.history_status.value,
                "drawdown_status": self._curve.drawdown_status.value,
                "complete": (
                    self._curve.history_status is ValuationStatus.FRESH
                ),
                "estimated": self._curve.stale_sample_count > 0,
                "sample_count": self._curve.sample_count,
                "available_sample_count": self._curve.available_sample_count,
                "stale_sample_count": self._curve.stale_sample_count,
                "unavailable_sample_count": self._curve.unavailable_sample_count,
            },
            "open_positions": [
                {
                    "token_id": position.token_id,
                    "size": _decimal_text(position.size),
                    "average_entry_price": _optional_decimal_text(
                        position.average_entry_price
                    ),
                    "executable_mark": _optional_decimal_text(
                        position.executable_mark
                    ),
                    "last_executable_mark": _optional_decimal_text(
                        position.last_executable_mark
                    ),
                    "market_value_usdc": _optional_decimal_text(
                        position.market_value_usdc
                    ),
                    "valuation_status": position.status.value,
                }
                for position in final_valuation.positions
            ],
            "artifacts": {
                "equity": EQUITY_FILE_NAME,
                "orders": ORDERS_FILE_NAME,
            },
        }

    def _provenance_json(self) -> dict[str, object]:
        return {
            "kind": self.provenance.kind.value,
            "bot_spec": self.provenance.bot_spec,
            "configuration": sanitized_configuration(
                self.provenance.configuration
            ),
            "seed": self.provenance.seed,
            "archive_sha256": self.provenance.archive_sha256,
            "archive_schema_version": self.provenance.archive_schema_version,
            "archive_target_identity": self.provenance.archive_target_identity,
        }

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

    def _required_equity_writer(self) -> csv.DictWriter[str]:
        writer = getattr(self, "_equity_writer", None)
        if writer is None or self._equity_file is None or self._equity_file.closed:
            raise PerformanceArtifactStateError("performance equity output is closed")
        return writer

    def _required_orders_writer(self) -> csv.DictWriter[str]:
        writer = getattr(self, "_orders_writer", None)
        if writer is None or self._orders_file is None or self._orders_file.closed:
            raise PerformanceArtifactStateError("performance orders output is closed")
        return writer

    def _flush_equity(self) -> None:
        if self._equity_file is not None and not self._equity_file.closed:
            self._equity_file.flush()

    def _flush_orders(self) -> None:
        if self._orders_file is not None and not self._orders_file.closed:
            self._orders_file.flush()

    def _close_csv_files(self) -> None:
        for output in (self._equity_file, self._orders_file):
            if output is not None and not output.closed:
                output.close()


def _validate_money(value: Decimal, name: str, *, positive: bool = False) -> None:
    if not value.is_finite() or (positive and value <= ZERO):
        requirement = "positive and finite" if positive else "finite"
        raise ValueError(f"performance {name} must be {requirement}")


def _decimal_text(value: Decimal) -> str:
    _validate_money(value, "decimal")
    return str(value)


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_text(value)
