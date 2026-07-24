import csv
import json
from datetime import datetime
from io import StringIO
from math import isnan
from pathlib import Path

import pytest
from rich.console import Console
from rich.text import Text

from polybot.cli.performance_chart.artifacts import load_performance_chart_data
from polybot.cli.performance_chart.command import main, print_performance_chart
from polybot.cli.performance_chart.contracts import (
    PerformanceChartData,
    PerformanceChartError,
)
from polybot.cli.performance_chart.rendering import render_performance_chart
from polybot.performance.contracts.files import (
    EQUITY_FIELDS,
    EQUITY_FILE_NAME,
    SUMMARY_FILE_NAME,
)
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    PerformanceRunStatus,
)
from polybot.performance.contracts.summary import (
    PerformanceSummaryV1,
)
from polybot.performance.contracts.summary.metrics import PerformanceMetricsSummary
from polybot.performance.contracts.summary.valuation import PerformanceValuationSummary
from polybot.performance.contracts.valuation_status import (
    ValuationStatus,
    history_valuation_status,
)


def _equity_row(
    timestamp_ms: int,
    pnl_usdc: str,
    valuation_status: str,
) -> dict[str, object]:
    return {
        "timestamp_ms": timestamp_ms,
        "sample_reason": "interval",
        "cash_usdc": "100",
        "marked_position_value_usdc": "0",
        "equity_usdc": "100",
        "pnl_usdc": pnl_usdc,
        "fees_usdc": "0",
        "exposure_usdc": "0",
        "position_count": 0,
        "valuation_status": valuation_status,
    }


def test_load_performance_chart_validates_and_projects_pnl_history(
    tmp_path: Path,
) -> None:
    results_dir = _results_dir(tmp_path)
    _write_equity(
        results_dir,
        (
            _equity_row(1_000, "0", "fresh"),
            _equity_row(1_000, "-1.25", "stale"),
            _equity_row(2_000, "", "unavailable"),
        ),
    )

    data = load_performance_chart_data(results_dir)

    assert tuple(data.timestamps_ms) == (1_000, 1_000, 2_000)
    assert tuple(data.pnl_values) == (0.0, -1.25, -1.25)
    assert tuple(data.stale_samples) == (False, True, True)


@pytest.mark.parametrize("value", ("NaN", "Infinity", "-Infinity", "invalid"))
def test_performance_summary_rejects_nonfinite_metric_values(value: str) -> None:
    payload = _summary_payload()
    metrics = dict(payload["metrics"])
    metrics["net_pnl_usdc"] = value
    payload["metrics"] = metrics

    with pytest.raises(ValueError, match="net_pnl_usdc must be a finite decimal"):
        PerformanceSummaryV1.from_dict(payload)


def test_performance_summary_normalizes_finite_state_fields() -> None:
    summary = PerformanceSummaryV1.from_dict(_summary_payload())

    assert summary.provenance.kind is PerformanceRunKind.BACKTEST
    assert isinstance(summary.metrics, PerformanceMetricsSummary)
    assert isinstance(summary.valuation, PerformanceValuationSummary)
    assert summary.valuation.final_status is ValuationStatus.FRESH


@pytest.mark.parametrize(
    ("stale_sample_count", "unavailable_sample_count", "expected"),
    (
        (0, 0, ValuationStatus.FRESH),
        (1, 0, ValuationStatus.STALE),
        (0, 1, ValuationStatus.UNAVAILABLE),
        (1, 1, ValuationStatus.UNAVAILABLE),
    ),
)
def test_history_valuation_status_derives_aggregate_from_counts(
    stale_sample_count: int,
    unavailable_sample_count: int,
    expected: ValuationStatus,
) -> None:
    assert (
        history_valuation_status(
            stale_sample_count=stale_sample_count,
            unavailable_sample_count=unavailable_sample_count,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("accepted_dispatch_count", 1, "dispatch outcomes exceed dispatch count"),
        ("fill_count", 6, "fills exceed order count"),
        ("rejected_order_count", 6, "rejected orders exceed order count"),
        (
            "coverage_gap_rejected_order_count",
            2,
            "coverage-gap rejections exceed rejected orders",
        ),
    ),
)
def test_performance_metrics_reject_inconsistent_aggregates(
    field: str,
    value: int,
    message: str,
) -> None:
    metrics = dict(_summary_payload()["metrics"])
    metrics[field] = value

    with pytest.raises(ValueError, match=message):
        PerformanceMetricsSummary.from_dict(metrics)


def test_performance_summary_rejects_inconsistent_derived_state() -> None:
    payload = _summary_payload()
    payload["partial"] = True

    with pytest.raises(ValueError, match="partial status is inconsistent"):
        PerformanceSummaryV1.from_dict(payload)

    payload = _summary_payload()
    valuation = dict(payload["valuation"])
    valuation["estimated"] = True
    payload["valuation"] = valuation

    with pytest.raises(ValueError, match="valuation estimate is inconsistent"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "complete", "estimated", "message"),
    (
        (
            "available_sample_count",
            0,
            True,
            False,
            "sample counts are inconsistent",
        ),
        (
            "stale_sample_count",
            2,
            True,
            True,
            "stale samples exceed available samples",
        ),
        (
            "history_status",
            "stale",
            False,
            False,
            "history status is inconsistent",
        ),
        (
            "drawdown_status",
            "stale",
            True,
            False,
            "drawdown status is inconsistent",
        ),
    ),
)
def test_performance_summary_rejects_impossible_valuation_aggregates(
    field: str,
    value: object,
    complete: bool,
    estimated: bool,
    message: str,
) -> None:
    payload = _summary_payload()
    valuation = dict(payload["valuation"])
    valuation[field] = value
    valuation["complete"] = complete
    valuation["estimated"] = estimated
    payload["valuation"] = valuation

    with pytest.raises(ValueError, match=message):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("status", "partial", "error"),
    (
        (PerformanceRunStatus.FAILED, True, None),
        (PerformanceRunStatus.COMPLETED, False, "unexpected failure"),
        (PerformanceRunStatus.CANCELLED, True, "unexpected failure"),
    ),
)
def test_performance_summary_rejects_invalid_terminal_error_contract(
    status: PerformanceRunStatus,
    partial: bool,
    error: str | None,
) -> None:
    payload = _summary_payload(status=status, partial=partial)
    payload["error"] = error

    with pytest.raises(ValueError, match="performance runs"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    "field",
    ("archive_sha256", "archive_schema_version", "archive_target_identity"),
)
def test_performance_summary_requires_backtest_archive_identity(field: str) -> None:
    payload = _summary_payload()
    provenance = dict(payload["provenance"])
    provenance[field] = None
    payload["provenance"] = provenance

    with pytest.raises(ValueError, match="provenance is invalid"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize("value", ("1E309", "9" * 309))
def test_performance_summary_rejects_unrenderable_decimal_metrics(value: str) -> None:
    payload = _summary_payload()
    metrics = dict(payload["metrics"])
    metrics["net_pnl_usdc"] = value
    payload["metrics"] = metrics

    with pytest.raises(ValueError, match="outside renderable bounds"):
        PerformanceSummaryV1.from_dict(payload)


def test_performance_summary_rejects_boolean_schema_version() -> None:
    payload = _summary_payload()
    payload["schema_version"] = True

    with pytest.raises(ValueError, match="unsupported performance summary schema version"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("section", "value"),
    (
        ("selection", {"start_ms": "bad"}),
        ("timing", {"started_at_ms": "bad"}),
        ("open_positions", [{}]),
        ("artifacts", {"equity": ["bad"]}),
    ),
)
def test_performance_summary_rejects_malformed_nested_contracts(
    section: str,
    value: object,
) -> None:
    payload = _summary_payload()
    payload[section] = value

    with pytest.raises(ValueError, match="performance summary"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            (
                _equity_row(2_000, "0", "fresh"),
                _equity_row(1_000, "0", "fresh"),
            ),
            "timestamp moves backward",
        ),
        ((_equity_row(1_000, "NaN", "fresh"),), "PnL is not finite"),
        ((_equity_row(1_000, "", "fresh"),), "PnL is missing"),
        ((_equity_row(1_000, "0", "unknown"),), "valuation status is invalid"),
        (
            (_equity_row(1 << 63, "0", "fresh"),),
            "timestamp is outside chart range",
        ),
    ],
)
def test_load_performance_chart_rejects_malformed_rows(
    tmp_path: Path,
    rows: tuple[dict[str, object], ...],
    message: str,
) -> None:
    results_dir = _results_dir(tmp_path)
    _write_equity(results_dir, rows)

    with pytest.raises(PerformanceChartError, match=message):
        load_performance_chart_data(results_dir)


def test_load_performance_chart_requires_exact_equity_header(tmp_path: Path) -> None:
    results_dir = _results_dir(tmp_path)
    (results_dir / EQUITY_FILE_NAME).write_text(
        "timestamp_ms,pnl_usdc\n1000,0\n",
        encoding="utf-8",
    )

    with pytest.raises(PerformanceChartError, match="header does not match schema"):
        load_performance_chart_data(results_dir)


def test_render_performance_chart_resamples_the_complete_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    summary = PerformanceSummaryV1.from_dict(_summary_payload())
    point_count = 1_000
    data = PerformanceChartData(
        results_dir=tmp_path,
        summary=summary,
        timestamps_ms=tuple(range(point_count)),
        pnl_values=tuple(float(value) for value in range(point_count)),
        stale_samples=tuple(False for _ in range(point_count)),
    )
    captured: dict[str, object] = {}

    def fake_render(series, colors, chart_height, empty_message, **kwargs):
        captured["series"] = series
        captured["minimum"] = kwargs["minimum"]
        captured["maximum"] = kwargs["maximum"]
        return Text("chart")

    monkeypatch.setattr(
        "polybot.cli.performance_chart.rendering.render_chart",
        fake_render,
    )

    render_performance_chart(data, width=80)

    current, stale = captured["series"]
    assert len(current) == 64
    assert current[0] == 0
    assert current[-1] == point_count - 1
    assert all(isnan(value) for value in stale)
    assert captured["minimum"] < 0
    assert captured["maximum"] > point_count - 1


def test_render_performance_chart_handles_an_all_missing_series(tmp_path: Path) -> None:
    summary = PerformanceSummaryV1.from_dict(_summary_payload())
    data = PerformanceChartData(
        results_dir=tmp_path,
        summary=summary,
        timestamps_ms=(1_000, 2_000),
        pnl_values=(float("nan"), float("nan")),
        stale_samples=(False, False),
    )
    output = StringIO()

    Console(file=output, width=80, force_terminal=False).print(
        render_performance_chart(data, width=80)
    )

    rendered = output.getvalue()
    assert "PnL unavailable" in rendered
    start_label = datetime.fromtimestamp(1).strftime("%H:%M:%S")
    end_label = datetime.fromtimestamp(2).strftime("%H:%M:%S")
    assert any(
        start_label in line and end_label in line
        for line in rendered.splitlines()
    )
    assert "Fills 4" in rendered
    assert "Orders 5" in rendered
    assert "Rejected 1" in rendered
    assert "Net PnL +$12.34" in rendered
    assert "Return +12.34%" in rendered
    assert "Drawdown $2.50" in rendered
    assert "Start $100.00" in rendered
    assert "End $112.34" in rendered


def test_saved_run_command_labels_partial_results(tmp_path: Path) -> None:
    results_dir = _results_dir(
        tmp_path,
        status=PerformanceRunStatus.FAILED,
        partial=True,
    )
    _write_equity(results_dir, (_equity_row(1_000, "-2", "fresh"),))
    output = StringIO()

    print_performance_chart(
        results_dir,
        console=Console(file=output, width=80, force_terminal=False),
    )

    rendered = output.getvalue()
    assert "Backtest net PnL" in rendered
    assert "failed (partial)" in rendered


def test_saved_run_command_exits_nonzero_for_missing_results(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path / "missing")])

    assert error.value.code == 2


def _results_dir(
    tmp_path: Path,
    *,
    status: PerformanceRunStatus = PerformanceRunStatus.COMPLETED,
    partial: bool = False,
) -> Path:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / SUMMARY_FILE_NAME).write_text(
        json.dumps(_summary_payload(status=status, partial=partial)),
        encoding="utf-8",
    )
    return results_dir


def _write_equity(
    results_dir: Path,
    rows: tuple[dict[str, object], ...],
) -> None:
    with (results_dir / EQUITY_FILE_NAME).open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=EQUITY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _summary_payload(
    *,
    status: PerformanceRunStatus = PerformanceRunStatus.COMPLETED,
    partial: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status.value,
        "partial": partial,
        "error": "stopped" if status is PerformanceRunStatus.FAILED else None,
        "provenance": {
            "kind": "backtest",
            "bot_spec": "tests:create",
            "configuration": {},
            "seed": 0,
            "archive_sha256": "archive",
            "archive_schema_version": 2,
            "archive_target_identity": "target",
        },
        "selection": {
            "session_id": 1,
            "start_ms": 1_000,
            "end_ms": 2_000,
            "market_slugs": ["market"],
            "replay_cutoff_sequence": None,
            "session_integrity_status": None,
            "uses_partial_session": False,
            "gap_policy": None,
            "coverage_gap_ids": [],
            "coverage_gap_count": 0,
            "coverage_gap_duration_ms": 0,
            "coverage_gap_open_count": 0,
            "coverage_gap_affected_position_token_ids": [],
            "coverage_gap_affected_position_count": 0,
        },
        "timing": {
            "started_at_ms": 1_000,
            "ended_at_ms": 2_000,
            "virtual_duration_ms": 1_000,
        },
        "metrics": {
            "initial_cash_usdc": "100",
            "initial_equity_usdc": "100",
            "final_cash_usdc": "100",
            "final_marked_position_value_usdc": "0",
            "final_equity_usdc": "112.34",
            "gross_pnl_usdc": "12.59",
            "net_pnl_usdc": "12.34",
            "return": "0.1234",
            "fees_usdc": "0.25",
            "filled_notional_usdc": "50",
            "max_drawdown_usdc": "2.5",
            "max_drawdown_fraction": "0.025",
            "order_count": 5,
            "fill_count": 4,
            "rejected_order_count": 1,
            "coverage_gap_rejected_order_count": 0,
            "resolution_count": 1,
            "event_count": 0,
            "dispatch_count": 0,
            "accepted_dispatch_count": 0,
            "skipped_dispatch_count": 0,
        },
        "valuation": {
            "final_status": "fresh",
            "history_status": "fresh",
            "drawdown_status": "fresh",
            "complete": True,
            "estimated": False,
            "sample_count": 1,
            "available_sample_count": 1,
            "stale_sample_count": 0,
            "unavailable_sample_count": 0,
        },
        "open_positions": [],
        "artifacts": {"equity": EQUITY_FILE_NAME, "orders": "orders.csv"},
    }
