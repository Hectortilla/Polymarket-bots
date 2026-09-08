import csv
import json
from datetime import datetime
from io import StringIO
from math import isnan
from pathlib import Path

import pytest
from polybot.cli.performance_chart.artifacts import load_performance_chart_data
from polybot.cli.performance_chart.command import main, print_performance_chart
from polybot.cli.performance_chart.contracts import (
    PerformanceChartData,
    PerformanceChartError,
)
from polybot.cli.performance_chart.rendering import (
    PNL_UNAVAILABLE_LABEL,
    render_performance_chart,
)
from polybot.performance.contracts.files import (
    EQUITY_FIELDS,
    EQUITY_FILE_NAME,
    ORDERS_FILE_NAME,
    RESULT_SCHEMA_VERSION,
    SUMMARY_FILE_NAME,
    EquityField,
    PerformanceArtifactField,
    PerformanceMetricsField,
    PerformanceProvenanceField,
    PerformanceSelectionField,
    PerformanceSummaryField,
    PerformanceTimingField,
    PerformanceValuationField,
)
from polybot.performance.contracts.run import (
    PerformanceRunKind,
    PerformanceRunStatus,
    SampleReason,
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
from rich.console import Console
from rich.text import Text


def _equity_row(
    timestamp_ms: int,
    pnl_usdc: str,
    valuation_status: str,
) -> dict[str, object]:
    return {
        EquityField.TIMESTAMP_MS: timestamp_ms,
        EquityField.SAMPLE_REASON: SampleReason.INTERVAL,
        EquityField.CASH_USDC: "100",
        EquityField.MARKED_POSITION_VALUE_USDC: "0",
        EquityField.EQUITY_USDC: "100",
        EquityField.PNL_USDC: pnl_usdc,
        EquityField.FEES_USDC: "0",
        EquityField.EXPOSURE_USDC: "0",
        EquityField.POSITION_COUNT: 0,
        EquityField.VALUATION_STATUS: valuation_status,
    }


def test_load_performance_chart_validates_and_projects_pnl_history(
    tmp_path: Path,
) -> None:
    results_dir = _results_dir(tmp_path)
    _write_equity(
        results_dir,
        (
            _equity_row(1_000, "0", ValuationStatus.FRESH),
            _equity_row(1_000, "-1.25", ValuationStatus.STALE),
            _equity_row(2_000, "", ValuationStatus.UNAVAILABLE),
        ),
    )

    data = load_performance_chart_data(results_dir)

    assert tuple(data.timestamps_ms) == (1_000, 1_000, 2_000)
    assert tuple(data.pnl_values) == (0.0, -1.25, -1.25)
    assert tuple(data.stale_samples) == (False, True, True)


@pytest.mark.parametrize("value", ("NaN", "Infinity", "-Infinity", "invalid"))
def test_performance_summary_rejects_nonfinite_metric_values(value: str) -> None:
    payload = _summary_payload()
    metrics = dict(payload[PerformanceSummaryField.METRICS])
    metrics[PerformanceMetricsField.NET_PNL_USDC] = value
    payload[PerformanceSummaryField.METRICS] = metrics

    with pytest.raises(ValueError, match="net_pnl_usdc must be a finite decimal"):
        PerformanceSummaryV1.from_dict(payload)


def test_performance_summary_normalizes_finite_state_fields() -> None:
    summary = PerformanceSummaryV1.from_dict(_summary_payload())

    assert summary.provenance.kind is PerformanceRunKind.BACKTEST
    assert isinstance(summary.metrics, PerformanceMetricsSummary)
    assert isinstance(summary.valuation, PerformanceValuationSummary)
    assert summary.valuation.final_status is ValuationStatus.FRESH


@pytest.mark.parametrize(
    (
        PerformanceValuationField.STALE_SAMPLE_COUNT,
        PerformanceValuationField.UNAVAILABLE_SAMPLE_COUNT,
        "expected",
    ),
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
        (
            PerformanceMetricsField.ACCEPTED_DISPATCH_COUNT,
            1,
            "dispatch outcomes exceed dispatch count",
        ),
        (PerformanceMetricsField.FILL_COUNT, 6, "fills exceed order count"),
        (
            PerformanceMetricsField.REJECTED_ORDER_COUNT,
            6,
            "rejected orders exceed order count",
        ),
        (
            PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT,
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
    metrics = dict(_summary_payload()[PerformanceSummaryField.METRICS])
    metrics[field] = value

    with pytest.raises(ValueError, match=message):
        PerformanceMetricsSummary.from_dict(metrics)


def test_performance_summary_rejects_inconsistent_derived_state() -> None:
    payload = _summary_payload()
    payload[PerformanceSummaryField.PARTIAL] = True

    with pytest.raises(ValueError, match="partial status is inconsistent"):
        PerformanceSummaryV1.from_dict(payload)

    payload = _summary_payload()
    valuation = dict(payload[PerformanceSummaryField.VALUATION])
    valuation[PerformanceValuationField.ESTIMATED] = True
    payload[PerformanceSummaryField.VALUATION] = valuation

    with pytest.raises(ValueError, match="valuation estimate is inconsistent"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value", "complete", "estimated", "message"),
    (
        (
            PerformanceValuationField.AVAILABLE_SAMPLE_COUNT,
            0,
            True,
            False,
            "sample counts are inconsistent",
        ),
        (
            PerformanceValuationField.STALE_SAMPLE_COUNT,
            2,
            True,
            True,
            "stale samples exceed available samples",
        ),
        (
            PerformanceValuationField.HISTORY_STATUS,
            ValuationStatus.STALE,
            False,
            False,
            "history status is inconsistent",
        ),
        (
            PerformanceValuationField.DRAWDOWN_STATUS,
            ValuationStatus.STALE,
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
    valuation = dict(payload[PerformanceSummaryField.VALUATION])
    valuation[field] = value
    valuation[PerformanceValuationField.COMPLETE] = complete
    valuation[PerformanceValuationField.ESTIMATED] = estimated
    payload[PerformanceSummaryField.VALUATION] = valuation

    with pytest.raises(ValueError, match=message):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("status", PerformanceSummaryField.PARTIAL, "error"),
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
    payload[PerformanceSummaryField.ERROR] = error

    with pytest.raises(ValueError, match="performance runs"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    "field",
    (
        PerformanceProvenanceField.ARCHIVE_SHA256,
        PerformanceProvenanceField.ARCHIVE_SCHEMA_VERSION,
        PerformanceProvenanceField.ARCHIVE_TARGET_IDENTITY,
    ),
)
def test_performance_summary_requires_backtest_archive_identity(field: str) -> None:
    payload = _summary_payload()
    provenance = dict(payload[PerformanceSummaryField.PROVENANCE])
    provenance[field] = None
    payload[PerformanceSummaryField.PROVENANCE] = provenance

    with pytest.raises(ValueError, match="provenance is invalid"):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize("value", ("1E309", "9" * 309))
def test_performance_summary_rejects_unrenderable_decimal_metrics(value: str) -> None:
    payload = _summary_payload()
    metrics = dict(payload[PerformanceSummaryField.METRICS])
    metrics[PerformanceMetricsField.NET_PNL_USDC] = value
    payload[PerformanceSummaryField.METRICS] = metrics

    with pytest.raises(ValueError, match="outside renderable bounds"):
        PerformanceSummaryV1.from_dict(payload)


def test_performance_summary_rejects_boolean_schema_version() -> None:
    payload = _summary_payload()
    payload[PerformanceSummaryField.SCHEMA_VERSION] = True

    with pytest.raises(
        ValueError, match="unsupported performance summary schema version"
    ):
        PerformanceSummaryV1.from_dict(payload)


@pytest.mark.parametrize(
    ("section", "value"),
    (
        (
            PerformanceSummaryField.SELECTION,
            {PerformanceSelectionField.START_MS: "bad"},
        ),
        (PerformanceSummaryField.TIMING, {PerformanceTimingField.STARTED_AT_MS: "bad"}),
        (PerformanceSummaryField.OPEN_POSITIONS, [{}]),
        (PerformanceSummaryField.ARTIFACTS, {PerformanceArtifactField.EQUITY: ["bad"]}),
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
                _equity_row(2_000, "0", ValuationStatus.FRESH),
                _equity_row(1_000, "0", ValuationStatus.FRESH),
            ),
            "timestamp moves backward",
        ),
        ((_equity_row(1_000, "NaN", ValuationStatus.FRESH),), "PnL is not finite"),
        ((_equity_row(1_000, "", ValuationStatus.FRESH),), "PnL is missing"),
        ((_equity_row(1_000, "0", "unknown"),), "valuation status is invalid"),
        (
            (_equity_row(1 << 63, "0", ValuationStatus.FRESH),),
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
    assert PNL_UNAVAILABLE_LABEL in rendered
    start_label = datetime.fromtimestamp(1).strftime("%H:%M:%S")
    end_label = datetime.fromtimestamp(2).strftime("%H:%M:%S")
    assert any(
        start_label in line and end_label in line for line in rendered.splitlines()
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
    _write_equity(results_dir, (_equity_row(1_000, "-2", ValuationStatus.FRESH),))
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
    with (results_dir / EQUITY_FILE_NAME).open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.DictWriter(output, fieldnames=EQUITY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _summary_payload(
    *,
    status: PerformanceRunStatus = PerformanceRunStatus.COMPLETED,
    partial: bool = False,
) -> dict[str, object]:
    return {
        PerformanceSummaryField.SCHEMA_VERSION: RESULT_SCHEMA_VERSION,
        PerformanceSummaryField.STATUS: status.value,
        PerformanceSummaryField.PARTIAL: partial,
        PerformanceSummaryField.ERROR: "stopped"
        if status is PerformanceRunStatus.FAILED
        else None,
        PerformanceSummaryField.PROVENANCE: {
            PerformanceProvenanceField.KIND: PerformanceRunKind.BACKTEST,
            PerformanceProvenanceField.BOT_SPEC: "tests:create",
            PerformanceProvenanceField.CONFIGURATION: {},
            PerformanceProvenanceField.SEED: 0,
            PerformanceProvenanceField.ARCHIVE_SHA256: "archive",
            PerformanceProvenanceField.ARCHIVE_SCHEMA_VERSION: 2,
            PerformanceProvenanceField.ARCHIVE_TARGET_IDENTITY: "target",
        },
        PerformanceSummaryField.SELECTION: {
            PerformanceSelectionField.SESSION_ID: 1,
            PerformanceSelectionField.START_MS: 1_000,
            PerformanceSelectionField.END_MS: 2_000,
            PerformanceSelectionField.MARKET_SLUGS: ["market"],
            PerformanceSelectionField.REPLAY_CUTOFF_SEQUENCE: None,
            PerformanceSelectionField.SESSION_INTEGRITY_STATUS: None,
            PerformanceSelectionField.USES_PARTIAL_SESSION: False,
            PerformanceSelectionField.GAP_POLICY: None,
            PerformanceSelectionField.COVERAGE_GAP_IDS: [],
            PerformanceSelectionField.COVERAGE_GAP_COUNT: 0,
            PerformanceSelectionField.COVERAGE_GAP_DURATION_MS: 0,
            PerformanceSelectionField.COVERAGE_GAP_OPEN_COUNT: 0,
            PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_TOKEN_IDS: [],
            PerformanceSelectionField.COVERAGE_GAP_AFFECTED_POSITION_COUNT: 0,
        },
        PerformanceSummaryField.TIMING: {
            PerformanceTimingField.STARTED_AT_MS: 1_000,
            PerformanceTimingField.ENDED_AT_MS: 2_000,
            PerformanceTimingField.VIRTUAL_DURATION_MS: 1_000,
        },
        PerformanceSummaryField.METRICS: {
            PerformanceMetricsField.INITIAL_CASH_USDC: "100",
            PerformanceMetricsField.INITIAL_EQUITY_USDC: "100",
            PerformanceMetricsField.FINAL_CASH_USDC: "100",
            PerformanceMetricsField.FINAL_MARKED_POSITION_VALUE_USDC: "0",
            PerformanceMetricsField.FINAL_EQUITY_USDC: "112.34",
            PerformanceMetricsField.GROSS_PNL_USDC: "12.59",
            PerformanceMetricsField.NET_PNL_USDC: "12.34",
            PerformanceMetricsField.RETURN_FRACTION: "0.1234",
            PerformanceMetricsField.FEES_USDC: "0.25",
            PerformanceMetricsField.FILLED_NOTIONAL_USDC: "50",
            PerformanceMetricsField.MAX_DRAWDOWN_USDC: "2.5",
            PerformanceMetricsField.MAX_DRAWDOWN_FRACTION: "0.025",
            PerformanceMetricsField.ORDER_COUNT: 5,
            PerformanceMetricsField.FILL_COUNT: 4,
            PerformanceMetricsField.REJECTED_ORDER_COUNT: 1,
            PerformanceMetricsField.COVERAGE_GAP_REJECTED_ORDER_COUNT: 0,
            PerformanceMetricsField.RESOLUTION_COUNT: 1,
            PerformanceMetricsField.EVENT_COUNT: 0,
            PerformanceMetricsField.DISPATCH_COUNT: 0,
            PerformanceMetricsField.ACCEPTED_DISPATCH_COUNT: 0,
            PerformanceMetricsField.SKIPPED_DISPATCH_COUNT: 0,
        },
        PerformanceSummaryField.VALUATION: {
            PerformanceValuationField.FINAL_STATUS: ValuationStatus.FRESH,
            PerformanceValuationField.HISTORY_STATUS: ValuationStatus.FRESH,
            PerformanceValuationField.DRAWDOWN_STATUS: ValuationStatus.FRESH,
            PerformanceValuationField.COMPLETE: True,
            PerformanceValuationField.ESTIMATED: False,
            PerformanceValuationField.SAMPLE_COUNT: 1,
            PerformanceValuationField.AVAILABLE_SAMPLE_COUNT: 1,
            PerformanceValuationField.STALE_SAMPLE_COUNT: 0,
            PerformanceValuationField.UNAVAILABLE_SAMPLE_COUNT: 0,
        },
        PerformanceSummaryField.OPEN_POSITIONS: [],
        PerformanceSummaryField.ARTIFACTS: {
            PerformanceArtifactField.EQUITY: EQUITY_FILE_NAME,
            PerformanceArtifactField.ORDERS: ORDERS_FILE_NAME,
        },
    }
