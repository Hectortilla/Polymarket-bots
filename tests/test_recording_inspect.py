from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from polybot.recording import inspect as inspect_cli
from polybot.recording.archive import RecordingArchive, RecordingReader
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    CoverageGapPayload,
    CoverageGapReason,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    RecordedBookLevel,
    RecordedEvent,
)
from polybot.recording.inspection import inspect_recording
from polybot.recording.identity import static_target_identity


MARKET_SLUG = "btc-updown-5m-1"
CONDITION_ID = "condition-1"
UP_TOKEN = "up-token"
DOWN_TOKEN = "down-token"


def _metadata() -> MarketMetadataPayload:
    return MarketMetadataPayload(
        market_id="market-1",
        condition_id=CONDITION_ID,
        market_slug=MARKET_SLUG,
        question="Will BTC go up?",
        events=(),
        outcomes=(
            MarketOutcomeMetadata("Up", UP_TOKEN),
            MarketOutcomeMetadata("Down", DOWN_TOKEN),
        ),
        active=True,
        closed=False,
        archived=False,
        start_at_ms=1_000,
        end_at_ms=301_000,
        closed_at_ms=None,
        order_book_enabled=True,
        accepting_orders=True,
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        seconds_delay=0,
        neg_risk=False,
        fees_enabled=False,
        fee_type=None,
        fee_schedule=None,
        fee_rate=Decimal("0"),
        question_id=None,
        neg_risk_request_id=None,
        resolution_status=None,
        resolution_source=None,
        resolved_by=None,
        resolved=False,
        winning_token_id=None,
        winning_outcome=None,
    )


def _identity(token_id: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        condition_id=CONDITION_ID,
        market_slug=MARKET_SLUG,
        token_id=token_id,
    )


def _book(token_id: str) -> BookBaselinePayload:
    return BookBaselinePayload(
        token_id=token_id,
        bids=(RecordedBookLevel(Decimal("0.4"), Decimal("10")),),
        asks=(RecordedBookLevel(Decimal("0.6"), Decimal("10")),),
    )


def _event(
    archive: RecordingArchive,
    payload: object,
    *,
    observed_at_ms: int,
    identity: MarketIdentity | None,
) -> RecordedEvent:
    return RecordedEvent(
        sequence=archive.next_sequence,
        session_id=archive.session_id,
        subscription_generation=0,
        observed_at_ms=observed_at_ms,
        source_timestamp_ms=None,
        identity=identity,
        payload=payload,  # type: ignore[arg-type]
    )


def _archive(path: Path) -> Path:
    archive = RecordingArchive.create(
        path,
        target_identity=static_target_identity((MARKET_SLUG,)),
        started_at_ms=1_000,
    )
    archive.append_event(
        _event(
            archive,
            _metadata(),
            observed_at_ms=1_000,
            identity=_identity(),
        )
    )
    for offset, token_id in enumerate((UP_TOKEN, DOWN_TOKEN), start=1):
        archive.append_event(
            _event(
                archive,
                _book(token_id),
                observed_at_ms=1_000 + (offset * 10),
                identity=_identity(token_id),
            )
        )
    archive.append_checkpoint(
        BookCheckpoint(
            sequence=archive.next_sequence - 1,
            session_id=archive.session_id,
            subscription_generation=0,
            observed_at_ms=1_025,
            identity=_identity(UP_TOKEN),
            book=_book(UP_TOKEN),
        )
    )
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.SDK_QUEUE_DROP,
                started_at_ms=1_030,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=1_030,
            identity=_identity(),
        )
    )
    archive.close_gap(gap_id, ended_at_ms=1_040)
    archive.close(ended_at_ms=1_040)
    return path


def test_reader_statistics_aggregate_without_decoding_events(tmp_path: Path) -> None:
    path = _archive(tmp_path / "capture.sqlite3")

    with RecordingReader(path) as reader:
        statistics = reader.statistics()

    assert len(statistics) == 1
    session = statistics[0]
    assert session.duration_ms == 20
    assert session.event_counts.market_metadata == 1
    assert session.event_counts.book_baseline == 2
    assert session.event_counts.coverage_gap == 1
    assert session.event_counts.replay_event_count == 3
    assert session.event_counts.stored_event_count == 4
    assert session.checkpoint_count == 1
    assert session.capture_anomaly_count == 0
    assert len(session.markets) == 1
    assert session.markets[0].market_slug == MARKET_SLUG
    assert session.markets[0].event_count == 3


def test_inspection_reports_archive_backtest_context(tmp_path: Path) -> None:
    path = _archive(tmp_path / "capture.sqlite3")

    inspection = inspect_recording(path)

    assert inspection.archive_path == path.resolve()
    assert inspection.archive_size_bytes > 0
    assert inspection.schema_version == 2
    assert inspection.market_count == 1
    assert inspection.captured_duration_ms == 20
    assert inspection.replay_event_count == 3
    assert inspection.checkpoint_count == 1
    assert inspection.gap_count == 1
    assert inspection.open_gap_count == 0
    assert inspection.known_anomaly_count == 0
    assert inspection.anomaly_unavailable_session_count == 0


def test_inspection_reports_legacy_anomaly_unavailability(tmp_path: Path) -> None:
    path = _archive(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE capture_anomalies")
        connection.execute("DROP TABLE recording_features")

    inspection = inspect_recording(path)

    assert inspection.known_anomaly_count == 0
    assert inspection.anomaly_unavailable_session_count == 1
    assert inspection.sessions[0].statistics.capture_anomaly_count is None


def test_inspection_takes_a_point_in_time_snapshot_of_an_active_archive(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity=static_target_identity((MARKET_SLUG,)),
        started_at_ms=1_000,
    )
    archive.append_event(
        _event(
            archive,
            _metadata(),
            observed_at_ms=1_000,
            identity=_identity(),
        )
    )
    try:
        inspection = inspect_recording(path)
    finally:
        archive.close(ended_at_ms=1_001)

    assert inspection.replay_event_count == 1
    assert (
        inspection.sessions[0].statistics.session.integrity_status.value == "active"
    )


def test_cli_prints_general_recording_information(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _archive(tmp_path / "capture.sqlite3")

    assert inspect_cli.main([str(path)]) == 0

    output = capsys.readouterr().out
    assert f"Recording: {path.resolve()}" in output
    assert "schema=v2" in output
    assert f"Target: static {MARKET_SLUG}" in output
    assert "sessions=1 markets=1 captured=0.020s events=3" in output
    assert "detected_gaps=1 open_gaps=0" in output
    assert "metadata=1 book_baselines=2" in output
    assert f"slug={MARKET_SLUG}" in output
    assert "reason=sdk_queue_drop" in output
    assert f"scope={MARKET_SLUG}" in output
    assert "Detected gaps require a clean selected range" in output
    assert "does not prove exchange-complete" not in output


def test_cli_rejects_a_missing_archive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit, match="2"):
        inspect_cli.main([str(tmp_path / "missing.sqlite3")])

    assert "recording archive does not exist" in capsys.readouterr().err
