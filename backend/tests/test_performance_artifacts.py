from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
from polybot.backtesting.contracts import BacktestGapPolicy
from polybot.cli.observability.events import (
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
)
from polybot.execution.paper.portfolio import PaperPortfolio, PaperPosition
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.performance.artifacts.errors import (
    PerformanceArtifactStateError,
    PerformanceOutputExistsError,
)
from polybot.performance.artifacts.lifecycle import (
    PerformanceArtifacts,
)
from polybot.performance.artifacts.sampling import PerformanceValuationSampler
from polybot.performance.contracts.files import (
    EQUITY_FILE_NAME,
    ORDERS_FILE_NAME,
    SUMMARY_FILE_NAME,
    EquityField,
    OrderField,
    PerformanceMetricsField,
    PerformancePositionField,
    PerformanceProvenanceField,
    PerformanceSelectionField,
    PerformanceSummaryField,
    PerformanceValuationField,
)
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
    SampleReason,
)
from polybot.performance.contracts.valuation_status import ValuationStatus
from polybot.performance.valuation import value_portfolio


def test_shared_valuation_marks_longs_at_bid_and_shorts_at_ask() -> None:
    portfolio = PortfolioSnapshot(
        cash_usdc=Decimal("100"),
        cumulative_fees_usdc=Decimal("0"),
        positions=(
            PortfolioPositionSnapshot("long", Decimal("2"), Decimal("0.50")),
            PortfolioPositionSnapshot("short", Decimal("-3"), Decimal("0.25")),
        ),
    )
    books = {
        "long": _book("long", "0.40", "0.60", received_at_ms=1_000),
        "short": _book("short", "0.20", "0.30", received_at_ms=1_000),
    }

    valuation = value_portfolio(
        portfolio,
        books,
        now_ms=1_000,
        max_book_age_ms=100,
        initial_cash_usdc=Decimal("100"),
    ).valuation

    assert valuation.status is ValuationStatus.FRESH
    assert valuation.marked_position_value_usdc == Decimal("-0.10")
    assert valuation.exposure_usdc == Decimal("1.70")
    assert valuation.equity_usdc == Decimal("99.90")
    assert valuation.pnl_usdc == Decimal("-0.10")
    assert valuation.positions[0].executable_mark == Decimal("0.40")
    assert valuation.positions[1].executable_mark == Decimal("0.30")


def test_valuation_labels_cached_marks_stale_and_missing_marks_unavailable() -> None:
    marks: dict[str, Decimal] = {}
    portfolio = PaperPortfolio(
        cash_usdc=Decimal("90"),
        positions={
            "held": PaperPosition("held", Decimal("2"), Decimal("0.50")),
        },
    )
    book = _book("held", "0.40", "0.60", received_at_ms=1_000)
    fresh_result = value_portfolio(
        portfolio,
        {"held": book},
        now_ms=1_000,
        max_book_age_ms=100,
        last_executable_marks=marks,
    )
    fresh = fresh_result.valuation
    marks = fresh_result.marks()
    stale = value_portfolio(
        portfolio,
        {"held": book},
        now_ms=1_101,
        max_book_age_ms=100,
        last_executable_marks=marks,
    ).valuation
    unavailable = value_portfolio(
        portfolio,
        {},
        now_ms=1_101,
        max_book_age_ms=100,
    ).valuation

    assert fresh.status is ValuationStatus.FRESH
    assert stale.status is ValuationStatus.STALE
    assert stale.positions[0].executable_mark is None
    assert stale.positions[0].last_executable_mark == Decimal("0.40")
    assert stale.equity_usdc == Decimal("90.80")
    assert unavailable.status is ValuationStatus.UNAVAILABLE
    assert unavailable.equity_usdc is None
    assert unavailable.positions[0].market_value_usdc is None


def test_out_of_order_sample_preserves_marks_and_curve() -> None:
    sampler = PerformanceValuationSampler(
        initial_cash_usdc=Decimal("100"),
        max_book_age_ms=1_000,
    )
    portfolio = PaperPortfolio(
        cash_usdc=Decimal("90"),
        positions={"held": PaperPosition("held", Decimal("2"), Decimal("0.50"))},
    )
    sampler.record_book(_book("held", "0.40", "0.60", received_at_ms=1_000))
    sampler.sample(1_000, SampleReason.START, portfolio)
    previous_curve = sampler.curve
    sampler.record_book(_book("held", "0.30", "0.50", received_at_ms=900))

    with pytest.raises(ValueError, match="timestamps must be nondecreasing"):
        sampler.sample(999, SampleReason.MANUAL, portfolio)

    assert sampler.curve is previous_curve
    assert sampler.last_executable_marks == {"held": Decimal("0.40")}
    sample = sampler.sample(1_000, SampleReason.MANUAL, portfolio)
    assert sample.valuation.equity_usdc == Decimal("90.60")
    assert sampler.last_executable_marks == {"held": Decimal("0.30")}
    assert sampler.curve.sample_count == 2


def test_performance_artifacts_stream_exact_rows_and_finalize_summary(
    tmp_path: Path,
) -> None:
    results_dir = tmp_path / "results"
    artifacts = PerformanceArtifacts(
        results_dir,
        provenance=_provenance(),
        selection=_selection(end_ms=5_000),
        initial_cash_usdc=Decimal("100.00"),
        report_interval_ms=1_000,
        max_book_age_ms=1_000,
    )
    initial = PaperPortfolio(Decimal("100.00"))
    artifacts.record_book(_book("token", "0.40", "0.60", received_at_ms=1_000))
    artifacts.start(1_000, initial)
    artifacts.advance_to(3_000, initial)

    order = OrderRequest(
        token_id="token",
        side=Side.BUY,
        price=Decimal("0.60"),
        size=Decimal("2.00"),
        market_slug="market",
        condition_id="condition",
        source_id="source-1",
        reason="entry",
    )
    fill = FillEvent(
        order_id="paper-1",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("2.00"),
        filled_size=Decimal("2.00"),
        average_price=Decimal("0.50"),
        fee_usdc=Decimal("0.10"),
        received_at_ms=3_000,
    )
    after_fill = PaperPortfolio(
        cash_usdc=Decimal("98.90"),
        cumulative_fees_usdc=Decimal("0.10"),
        positions={"token": PaperPosition("token", Decimal("2.00"), Decimal("0.50"))},
    )
    artifacts.record_order_result(
        submitted_at_ms=2_900,
        order=order,
        fill=fill,
    )
    artifacts.record_book(_book("token", "0.40", "0.60", received_at_ms=3_000))
    artifacts.record_transaction(3_000, SampleReason.FILL, after_fill)
    rejected_order = OrderRequest(
        token_id="token",
        side=Side.SELL,
        price=Decimal("0.30"),
        size=Decimal("1.00"),
        reason="bad-exit",
    )
    artifacts.record_order_result(
        submitted_at_ms=3_050,
        order=rejected_order,
        fill=FillEvent.rejected(
            order_id="paper-2",
            token_id="token",
            side=Side.SELL,
            requested_size=Decimal("1.00"),
            received_at_ms=3_100,
            reject_reason=FillRejectReason.BOOK_STALE,
            reject_message=ValuationStatus.STALE,
        ),
    )
    artifacts.record_book(_book("token", "0.30", "0.60", received_at_ms=4_000))
    artifacts.counters.record_events(3)
    artifacts.counters.record_dispatch(True)
    artifacts.counters.record_dispatch(False)
    artifacts.counters.record_dispatch(None)
    artifacts.counters.record_resolutions()

    summary = artifacts.finalize(
        status=PerformanceRunStatus.COMPLETED,
        ended_at_ms=5_000,
        portfolio=after_fill,
    )

    with (results_dir / EQUITY_FILE_NAME).open(newline="", encoding="utf-8") as source:
        equity_rows = list(csv.DictReader(source))
    with (results_dir / ORDERS_FILE_NAME).open(newline="", encoding="utf-8") as source:
        order_rows = list(csv.DictReader(source))
    stored_summary = json.loads((results_dir / SUMMARY_FILE_NAME).read_text())

    assert [int(row[EquityField.TIMESTAMP_MS]) for row in equity_rows] == [
        1_000,
        2_000,
        3_000,
        3_000,
        4_000,
        5_000,
        5_000,
    ]
    assert equity_rows[3] == {
        EquityField.TIMESTAMP_MS: "3000",
        EquityField.SAMPLE_REASON: SampleReason.FILL,
        EquityField.CASH_USDC: "98.90",
        EquityField.MARKED_POSITION_VALUE_USDC: "0.8000",
        EquityField.EQUITY_USDC: "99.7000",
        EquityField.PNL_USDC: "-0.3000",
        EquityField.FEES_USDC: "0.10",
        EquityField.EXPOSURE_USDC: "0.8000",
        EquityField.POSITION_COUNT: "1",
        EquityField.VALUATION_STATUS: ValuationStatus.FRESH,
    }
    assert order_rows[0][OrderField.REQUESTED_PRICE] == "0.60"
    assert order_rows[0][OrderField.AVERAGE_PRICE] == "0.50"
    assert order_rows[0][OrderField.STRATEGY_REASON] == "entry"
    assert order_rows[1][OrderField.REJECT_REASON] == FillRejectReason.BOOK_STALE.value
    assert summary == stored_summary
    assert summary[PerformanceSummaryField.STATUS] == PerformanceRunStatus.COMPLETED
    assert summary[PerformanceSummaryField.PARTIAL] is False
    assert summary[PerformanceSummaryField.METRICS] == {
        PerformanceMetricsField.INITIAL_CASH_USDC: "100.00",
        PerformanceMetricsField.INITIAL_EQUITY_USDC: "100.00",
        PerformanceMetricsField.FINAL_CASH_USDC: "98.90",
        PerformanceMetricsField.FINAL_MARKED_POSITION_VALUE_USDC: "0.6000",
        PerformanceMetricsField.FINAL_EQUITY_USDC: "99.5000",
        PerformanceMetricsField.GROSS_PNL_USDC: "-0.4000",
        PerformanceMetricsField.NET_PNL_USDC: "-0.5000",
        PerformanceMetricsField.RETURN_FRACTION: "-0.005",
        PerformanceMetricsField.FEES_USDC: "0.10",
        PerformanceMetricsField.FILLED_NOTIONAL_USDC: "1.0000",
        PerformanceMetricsField.MAX_DRAWDOWN_USDC: "0.5000",
        PerformanceMetricsField.MAX_DRAWDOWN_FRACTION: "0.005",
        PerformanceMetricsField.ORDER_COUNT: 2,
        PerformanceMetricsField.FILL_COUNT: 1,
        PerformanceMetricsField.REJECTED_ORDER_COUNT: 1,
        PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT: 0,
        PerformanceMetricsField.RESOLUTION_COUNT: 1,
        PerformanceMetricsField.EVENT_COUNT: 3,
        PerformanceMetricsField.DISPATCH_COUNT: 3,
        PerformanceMetricsField.ACCEPTED_DISPATCH_COUNT: 1,
        PerformanceMetricsField.SKIPPED_DISPATCH_COUNT: 1,
    }
    assert (
        summary[PerformanceSummaryField.VALUATION][
            PerformanceValuationField.FINAL_STATUS
        ]
        == ValuationStatus.FRESH
    )
    assert summary[PerformanceSummaryField.OPEN_POSITIONS] == [
        {
            PerformancePositionField.TOKEN_ID: "token",
            PerformancePositionField.SIZE: "2.00",
            PerformancePositionField.AVERAGE_ENTRY_PRICE: "0.50",
            PerformancePositionField.EXECUTABLE_MARK: "0.30",
            PerformancePositionField.LAST_EXECUTABLE_MARK: None,
            PerformancePositionField.MARKET_VALUE_USDC: "0.6000",
            PerformancePositionField.VALUATION_STATUS: ValuationStatus.FRESH,
        }
    ]
    assert (
        "private_key"
        not in summary[PerformanceSummaryField.PROVENANCE][
            PerformanceProvenanceField.CONFIGURATION
        ]
    )
    assert (
        "api_secret"
        not in summary[PerformanceSummaryField.PROVENANCE][
            PerformanceProvenanceField.CONFIGURATION
        ]
    )
    assert not tuple(results_dir.glob(f".{SUMMARY_FILE_NAME}.*"))
    with pytest.raises(PerformanceArtifactStateError, match="finalized"):
        artifacts.record_book(_book("token", "0.3", "0.6"))


def test_blackout_gap_provenance_and_effects_are_durable(tmp_path: Path) -> None:
    artifacts = PerformanceArtifacts(
        tmp_path / "blackout",
        provenance=_provenance(),
        selection=RunSelection(
            session_id=1,
            start_ms=1_000,
            end_ms=2_000,
            market_slugs=("market",),
            gap_policy=" blackout ",
            coverage_gap_ids=(9, 3, 9),
            coverage_gap_duration_ms=125,
            coverage_gap_open_count=1,
        ),
        initial_cash_usdc=Decimal("100"),
    )
    portfolio = PaperPortfolio(Decimal("100"))
    artifacts.start(1_000, portfolio)
    artifacts.record_coverage_gap_affected_positions(("token-b", "token-a"))
    artifacts.record_coverage_gap_affected_positions(("token-a",))
    artifacts.record_order_result(
        submitted_at_ms=1_000,
        order=OrderRequest(
            token_id="token-a",
            side=Side.BUY,
            price=Decimal("0.60"),
            size=Decimal("1"),
        ),
        fill=FillEvent.rejected(
            order_id="paper-1",
            token_id="token-a",
            side=Side.BUY,
            requested_size=Decimal("1"),
            received_at_ms=1_000,
            reject_reason=FillRejectReason.BACKTEST_COVERAGE_GAP,
            reject_message="recorded coverage gap crossed order latency",
        ),
    )

    summary = artifacts.finalize(
        status=PerformanceRunStatus.COMPLETED,
        ended_at_ms=2_000,
        portfolio=portfolio,
    )

    assert summary[PerformanceSummaryField.SELECTION] == {
        PerformanceSelectionField.SESSION_ID: 1,
        PerformanceSelectionField.START_MS: 1_000,
        PerformanceSelectionField.END_MS: 2_000,
        PerformanceSelectionField.MARKET_SLUGS: ["market"],
        PerformanceSelectionField.REPLAY_CUTOFF_SEQUENCE: None,
        PerformanceSelectionField.SESSION_INTEGRITY_STATUS: None,
        PerformanceSelectionField.USES_PARTIAL_SESSION: False,
        PerformanceSelectionField.GAP_POLICY: BacktestGapPolicy.BLACKOUT,
        PerformanceSelectionField.COVERAGE_GAP_IDS: [3, 9],
        PerformanceSelectionField.COVERAGE_GAP_COUNT: 2,
        PerformanceSelectionField.COVERAGE_GAP_DURATION_MS: 125,
        PerformanceSelectionField.COVERAGE_GAP_OPEN_COUNT: 1,
        PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS: [
            "token-a",
            "token-b",
        ],
        PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_COUNT: 2,
    }
    assert (
        summary[PerformanceSummaryField.METRICS][
            PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT
        ]
        == 1
    )


def test_run_selection_rejects_gap_provenance_without_policy() -> None:
    with pytest.raises(ValueError, match="require a gap policy"):
        RunSelection(
            session_id=1,
            start_ms=1_000,
            end_ms=2_000,
            market_slugs=("market",),
            coverage_gap_ids=(1,),
        )


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (PerformanceRunStatus.FAILED, "strategy exploded"),
        (PerformanceRunStatus.CANCELLED, None),
    ],
)
def test_partial_run_status_is_durable(
    tmp_path: Path,
    status: PerformanceRunStatus,
    error: str | None,
) -> None:
    artifacts = PerformanceArtifacts(
        tmp_path / status.value,
        provenance=_provenance(),
        selection=_selection(end_ms=1_000),
        initial_cash_usdc=Decimal("100"),
    )
    portfolio = PaperPortfolio(Decimal("100"))
    artifacts.start(1_000, portfolio)

    summary = artifacts.finalize(
        status=status,
        ended_at_ms=1_000,
        portfolio=portfolio,
        error=error,
    )

    assert summary[PerformanceSummaryField.STATUS] == status.value
    assert summary[PerformanceSummaryField.PARTIAL] is True
    assert summary[PerformanceSummaryField.ERROR] == error


def test_stale_open_position_is_estimated_and_not_complete(tmp_path: Path) -> None:
    artifacts = PerformanceArtifacts(
        tmp_path / ValuationStatus.STALE,
        provenance=_provenance(),
        selection=_selection(end_ms=1_001),
        initial_cash_usdc=Decimal("100"),
        max_book_age_ms=0,
    )
    initial = PaperPortfolio(Decimal("100"))
    held = PaperPortfolio(
        cash_usdc=Decimal("99"),
        positions={"token": PaperPosition("token", Decimal("2"), Decimal("0.50"))},
    )
    artifacts.record_book(_book("token", "0.40", "0.60"))
    artifacts.start(1_000, initial)
    artifacts.record_transaction(1_000, SampleReason.FILL, held)

    summary = artifacts.finalize(
        status=PerformanceRunStatus.COMPLETED,
        ended_at_ms=1_001,
        portfolio=held,
    )

    assert (
        summary[PerformanceSummaryField.VALUATION][
            PerformanceValuationField.FINAL_STATUS
        ]
        == ValuationStatus.STALE
    )
    assert (
        summary[PerformanceSummaryField.VALUATION][PerformanceValuationField.ESTIMATED]
        is True
    )
    assert (
        summary[PerformanceSummaryField.VALUATION][PerformanceValuationField.COMPLETE]
        is False
    )
    assert (
        summary[PerformanceSummaryField.OPEN_POSITIONS][0][
            PerformancePositionField.EXECUTABLE_MARK
        ]
        is None
    )
    assert (
        summary[PerformanceSummaryField.OPEN_POSITIONS][0][
            PerformancePositionField.LAST_EXECUTABLE_MARK
        ]
        == "0.40"
    )


def test_reused_idempotent_fill_is_not_double_counted(tmp_path: Path) -> None:
    artifacts = PerformanceArtifacts(
        tmp_path / "idempotent",
        provenance=_provenance(),
        selection=_selection(end_ms=1_000),
        initial_cash_usdc=Decimal("100"),
    )
    initial = PaperPortfolio(Decimal("100"))
    filled = PaperPortfolio(
        cash_usdc=Decimal("99.40"),
        positions={"token": PaperPosition("token", Decimal("1"), Decimal("0.60"))},
    )
    order = OrderRequest(
        token_id="token",
        side=Side.BUY,
        price=Decimal("0.60"),
        size=Decimal("1"),
        source_id="same-source",
    )
    fill = FillEvent(
        order_id="paper-1",
        token_id="token",
        side=Side.BUY,
        status=OrderStatus.FILLED,
        requested_size=Decimal("1"),
        filled_size=Decimal("1"),
        average_price=Decimal("0.60"),
        fee_usdc=Decimal("0"),
        received_at_ms=1_000,
    )
    artifacts.record_book(_book("token", "0.40", "0.60"))
    artifacts.start(1_000, initial)
    artifacts.record_fill(
        submitted_at_ms=1_000,
        order=order,
        fill=fill,
        portfolio=filled,
    )
    artifacts.record_fill(
        submitted_at_ms=1_000,
        order=order,
        fill=fill,
        portfolio=filled,
    )

    summary = artifacts.finalize(
        status=PerformanceRunStatus.COMPLETED,
        ended_at_ms=1_000,
        portfolio=filled,
    )

    assert (
        summary[PerformanceSummaryField.METRICS][PerformanceMetricsField.ORDER_COUNT]
        == 2
    )
    assert (
        summary[PerformanceSummaryField.METRICS][PerformanceMetricsField.FILL_COUNT]
        == 1
    )
    assert (
        summary[PerformanceSummaryField.METRICS][
            PerformanceMetricsField.FILLED_NOTIONAL_USDC
        ]
        == "0.60"
    )


def test_existing_results_directory_is_refused(tmp_path: Path) -> None:
    results_dir = tmp_path / "existing"
    artifacts = PerformanceArtifacts(
        results_dir,
        provenance=_provenance(),
        selection=_selection(end_ms=1_000),
        initial_cash_usdc=Decimal("100"),
    )

    with pytest.raises(PerformanceOutputExistsError, match="already exists"):
        PerformanceArtifacts(
            results_dir,
            provenance=_provenance(),
            selection=_selection(end_ms=1_000),
            initial_cash_usdc=Decimal("100"),
        )

    portfolio = PaperPortfolio(Decimal("100"))
    artifacts.start(1_000, portfolio)
    artifacts.finalize(
        status=PerformanceRunStatus.COMPLETED,
        ended_at_ms=1_000,
        portfolio=portfolio,
    )


def _provenance() -> RunProvenance:
    return RunProvenance(
        kind=PerformanceRunKind.BACKTEST,
        bot_spec="tests.bot:create",
        configuration={
            "name": "test",
            "max_order_size": Decimal("2.00"),
            "private_key": "never-write-me",
            "api_secret": "never-write-me-either",
        },
        seed=0,
        archive_sha256="a" * 64,
        archive_schema_version=2,
        archive_target_identity="target",
    )


def _selection(*, end_ms: int) -> RunSelection:
    return RunSelection(
        session_id=1,
        start_ms=1_000,
        end_ms=end_ms,
        market_slugs=("market",),
    )


def _book(
    token_id: str,
    bid: str,
    ask: str,
    *,
    received_at_ms: int = 1_000,
) -> BookSnapshot:
    return BookSnapshot(
        token_id=token_id,
        bids=(BookLevel(Decimal(bid), Decimal("10")),),
        asks=(BookLevel(Decimal(ask), Decimal("10")),),
        received_at_ms=received_at_ms,
        market_slug="market",
        condition_id="condition",
    )
