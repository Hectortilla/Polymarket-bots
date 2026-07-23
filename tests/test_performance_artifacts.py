from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

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
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    PerformanceRunStatus,
    RunProvenance,
    RunSelection,
    SampleReason,
)
from polybot.performance.valuation import ValuationStatus, value_portfolio


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
        positions={
            "token": PaperPosition("token", Decimal("2.00"), Decimal("0.50"))
        },
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
            reject_message="stale",
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

    with (results_dir / "equity.csv").open(newline="", encoding="utf-8") as source:
        equity_rows = list(csv.DictReader(source))
    with (results_dir / "orders.csv").open(newline="", encoding="utf-8") as source:
        order_rows = list(csv.DictReader(source))
    stored_summary = json.loads((results_dir / "summary.json").read_text())

    assert [int(row["timestamp_ms"]) for row in equity_rows] == [
        1_000,
        2_000,
        3_000,
        3_000,
        4_000,
        5_000,
        5_000,
    ]
    assert equity_rows[3] == {
        "timestamp_ms": "3000",
        "sample_reason": "fill",
        "cash_usdc": "98.90",
        "marked_position_value_usdc": "0.8000",
        "equity_usdc": "99.7000",
        "pnl_usdc": "-0.3000",
        "fees_usdc": "0.10",
        "exposure_usdc": "0.8000",
        "position_count": "1",
        "valuation_status": "fresh",
    }
    assert order_rows[0]["requested_price"] == "0.60"
    assert order_rows[0]["average_price"] == "0.50"
    assert order_rows[0]["strategy_reason"] == "entry"
    assert order_rows[1]["reject_reason"] == "book_stale"
    assert summary == stored_summary
    assert summary["status"] == "completed"
    assert summary["partial"] is False
    assert summary["metrics"] == {
        "initial_cash_usdc": "100.00",
        "initial_equity_usdc": "100.00",
        "final_cash_usdc": "98.90",
        "final_marked_position_value_usdc": "0.6000",
        "final_equity_usdc": "99.5000",
        "gross_pnl_usdc": "-0.4000",
        "net_pnl_usdc": "-0.5000",
        "return": "-0.005",
        "fees_usdc": "0.10",
        "filled_notional_usdc": "1.0000",
        "max_drawdown_usdc": "0.5000",
        "max_drawdown_fraction": "0.005",
        "order_count": 2,
        "fill_count": 1,
        "rejected_order_count": 1,
        "coverage_gap_rejected_order_count": 0,
        "resolution_count": 1,
        "event_count": 3,
        "dispatch_count": 3,
        "accepted_dispatch_count": 1,
        "skipped_dispatch_count": 1,
    }
    assert summary["valuation"]["final_status"] == "fresh"
    assert summary["open_positions"] == [
        {
            "token_id": "token",
            "size": "2.00",
            "average_entry_price": "0.50",
            "executable_mark": "0.30",
            "last_executable_mark": None,
            "market_value_usdc": "0.6000",
            "valuation_status": "fresh",
        }
    ]
    assert "private_key" not in summary["provenance"]["configuration"]
    assert "api_secret" not in summary["provenance"]["configuration"]
    assert not tuple(results_dir.glob(".summary.json.*"))
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

    assert summary["selection"] == {
        "session_id": 1,
        "start_ms": 1_000,
        "end_ms": 2_000,
        "market_slugs": ["market"],
        "replay_cutoff_sequence": None,
        "session_integrity_status": None,
        "uses_partial_session": False,
        "gap_policy": "blackout",
        "coverage_gap_ids": [3, 9],
        "coverage_gap_count": 2,
        "coverage_gap_duration_ms": 125,
        "coverage_gap_open_count": 1,
        "coverage_gap_affected_position_token_ids": ["token-a", "token-b"],
        "coverage_gap_affected_position_count": 2,
    }
    assert summary["metrics"]["coverage_gap_rejected_order_count"] == 1


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

    assert summary["status"] == status.value
    assert summary["partial"] is True
    assert summary["error"] == error


def test_stale_open_position_is_estimated_and_not_complete(tmp_path: Path) -> None:
    artifacts = PerformanceArtifacts(
        tmp_path / "stale",
        provenance=_provenance(),
        selection=_selection(end_ms=1_001),
        initial_cash_usdc=Decimal("100"),
        max_book_age_ms=0,
    )
    initial = PaperPortfolio(Decimal("100"))
    held = PaperPortfolio(
        cash_usdc=Decimal("99"),
        positions={
            "token": PaperPosition("token", Decimal("2"), Decimal("0.50"))
        },
    )
    artifacts.record_book(_book("token", "0.40", "0.60"))
    artifacts.start(1_000, initial)
    artifacts.record_transaction(1_000, SampleReason.FILL, held)

    summary = artifacts.finalize(
        status=PerformanceRunStatus.COMPLETED,
        ended_at_ms=1_001,
        portfolio=held,
    )

    assert summary["valuation"]["final_status"] == "stale"
    assert summary["valuation"]["estimated"] is True
    assert summary["valuation"]["complete"] is False
    assert summary["open_positions"][0]["executable_mark"] is None
    assert summary["open_positions"][0]["last_executable_mark"] == "0.40"


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
        positions={
            "token": PaperPosition("token", Decimal("1"), Decimal("0.60"))
        },
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

    assert summary["metrics"]["order_count"] == 2
    assert summary["metrics"]["fill_count"] == 1
    assert summary["metrics"]["filled_notional_usdc"] == "0.60"


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
