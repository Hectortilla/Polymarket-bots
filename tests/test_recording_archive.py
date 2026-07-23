from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import replace
from decimal import Decimal

import pytest

from polybot.framework.events import Side
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.markets import Market, MarketOutcome
from polybot.recording.archive.errors import (
    ArchiveCoverageError,
    ArchiveExistsError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
    CaptureAnomalyJournalUnavailableError,
)
from polybot.recording.archive.reader import RecordingReader
from polybot.recording.archive.schema import SCHEMA_VERSION
from polybot.recording.archive.writer import RecordingArchive
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    RecordedBookLevel,
    TickSizeChangePayload,
)
from polybot.recording.contracts.records import (
    BookCheckpoint,
    RecordedEvent,
)
from polybot.recording.contracts.anomalies import (
    CaptureAnomalyFragment,
    CaptureAnomalyPayload,
    CaptureBookDiagnostics,
    CaptureFailureKind,
    CaptureFragmentRole,
    RevisionFingerprint,
)
from polybot.recording.contracts.gaps import (
    CoverageGapPayload,
    CoverageGapReason,
)
from polybot.recording.contracts.market import (
    FeeScheduleMetadata,
    MarketEventMetadata,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
)
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)
from polybot.recording.contracts.session import SessionIntegrityStatus
from polybot.recording.archive.models import RecordingSession
from polybot.recording.coverage import CoverageScope
from polybot.recording.contracts.kinds import PayloadKind
from polybot.recording.serialization.entrypoints import (
    capture_anomaly_from_json,
    capture_anomaly_json,
    payload_from_json,
    payload_json,
)
from polybot.recording.serialization.registry import payload_kind
from polybot.recording.writer import AsyncRecordingWriter


@pytest.mark.parametrize(
    ("status", "ended_at_ms", "clean_close", "failure_reason"),
    (
        (SessionIntegrityStatus.ACTIVE, 2, False, None),
        (SessionIntegrityStatus.ACTIVE, None, True, None),
        (SessionIntegrityStatus.COMPLETE, None, True, None),
        (SessionIntegrityStatus.COMPLETE, 2, False, None),
        (SessionIntegrityStatus.FAILED, 2, True, "failure"),
        (SessionIntegrityStatus.FAILED, 2, False, None),
        (SessionIntegrityStatus.INCOMPLETE, 2, True, "failure"),
        (SessionIntegrityStatus.INCOMPLETE, 2, False, None),
    ),
)
def test_recording_session_rejects_inconsistent_integrity_fields(
    status: SessionIntegrityStatus,
    ended_at_ms: int | None,
    clean_close: bool,
    failure_reason: str | None,
) -> None:
    with pytest.raises(ValueError, match="integrity fields"):
        RecordingSession(
            session_id=1,
            started_at_ms=1,
            ended_at_ms=ended_at_ms,
            clean_close=clean_close,
            integrity_status=status,
            recorder_version="1",
            sdk_version="1",
            failure_reason=failure_reason,
        )


def test_coverage_scope_falls_back_to_event_identity() -> None:
    scope = CoverageScope.from_gap(
        CoverageGapPayload(
            reason=CoverageGapReason.SDK_QUEUE_DROP,
            started_at_ms=1,
            ended_at_ms=None,
        ),
        MarketIdentity(
            condition_id="condition-1",
            market_slug="market-1",
            token_id="token-1",
        ),
    )

    assert not scope.is_global
    assert scope.affects(
        condition_ids=("condition-1",),
        market_slugs=("market-1",),
        token_id="token-1",
    )
    assert not scope.affects(
        condition_ids=("condition-2",),
        market_slugs=("market-1",),
        token_id="token-1",
    )


def _metadata(*, condition_id: str = "condition-1") -> MarketMetadataPayload:
    return MarketMetadataPayload(
        market_id="gamma-market-1",
        condition_id=condition_id,
        market_slug="btc-updown-5m-1",
        question="Will BTC go up?",
        events=(
            MarketEventMetadata(
                event_id="event-1",
                slug="btc-five-minute",
                title="BTC five-minute markets",
            ),
        ),
        outcomes=(
            MarketOutcomeMetadata("Up", "up-token", Decimal("0.4200")),
            MarketOutcomeMetadata("Down", "down-token", Decimal("0.5800")),
        ),
        active=True,
        closed=False,
        archived=False,
        start_at_ms=1_000,
        end_at_ms=301_000,
        closed_at_ms=None,
        order_book_enabled=True,
        accepting_orders=True,
        minimum_tick_size=Decimal("0.0100"),
        minimum_order_size=Decimal("5.000"),
        seconds_delay=0,
        neg_risk=False,
        fees_enabled=True,
        fee_type="curve",
        fee_schedule=FeeScheduleMetadata(
            exponent=Decimal("2.00"),
            rate=Decimal("0.2500"),
            taker_only=True,
            rebate_rate=Decimal("0.000"),
        ),
        fee_rate=Decimal("0.2500"),
        question_id="question-1",
        neg_risk_request_id=None,
        resolution_status=None,
        resolution_source="https://example.test/rules",
        resolved_by=None,
        resolved=False,
        winning_token_id=None,
        winning_outcome=None,
    )


def _identity(token_id: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        condition_id="condition-1",
        market_slug="btc-updown-5m-1",
        token_id=token_id,
    )


def _baseline(token_id: str = "up-token") -> BookBaselinePayload:
    return BookBaselinePayload(
        token_id=token_id,
        bids=(
            RecordedBookLevel(Decimal("0.4200"), Decimal("12.500")),
            RecordedBookLevel(Decimal("0.4100"), Decimal("7.0")),
        ),
        asks=(RecordedBookLevel(Decimal("0.4300"), Decimal("9.25")),),
        source_hash="book-hash",
    )


def _event(
    archive: RecordingArchive,
    payload: object,
    *,
    observed_at_ms: int,
    identity: MarketIdentity | None,
    generation: int = 0,
    source_timestamp_ms: int | None = None,
) -> RecordedEvent:
    return RecordedEvent(
        sequence=archive.next_sequence,
        session_id=archive.session_id,
        subscription_generation=generation,
        observed_at_ms=observed_at_ms,
        source_timestamp_ms=source_timestamp_ms,
        identity=identity,
        payload=payload,  # type: ignore[arg-type]
    )


def _opened_archive(tmp_path) -> tuple[RecordingArchive, int]:
    started_at_ms = time.time_ns() // 1_000_000
    return (
        RecordingArchive.create(
            tmp_path / "capture.sqlite3",
            target_identity="slugs:btc-updown-5m-1",
            started_at_ms=started_at_ms,
        ),
        started_at_ms,
    )


def _capture_anomaly(
    *,
    failure_kind: CaptureFailureKind = CaptureFailureKind.SPLIT_REVISION_MISMATCH,
) -> CaptureAnomalyPayload:
    delta = BookDeltaPayload(
        changes=(
            BookChange(
                token_id="up-token",
                side=Side.SELL,
                price=Decimal("0.4200"),
                size=Decimal("8.500"),
                source_hash="up-hash",
                best_bid=Decimal("0.4300"),
                best_ask=Decimal("0.4200"),
            ),
        )
    )
    return CaptureAnomalyPayload(
        failure_kind=failure_kind,
        expected_fingerprint=RevisionFingerprint(
            condition_id="condition-1",
            source_timestamp_ms=12_345,
            source_hashes=(("up-token", "up-hash"),),
        ),
        actual_fingerprint=None,
        fragments=(
            CaptureAnomalyFragment(
                role=CaptureFragmentRole.INITIAL,
                source_timestamp_ms=12_345,
                identity=_identity("up-token"),
                payload=delta,
            ),
        ),
        book_diagnostics=(
            CaptureBookDiagnostics(
                token_id="up-token",
                projected_best_bid=Decimal("0.4100"),
                projected_best_ask=Decimal("0.4200"),
                advertised_best_bid=Decimal("0.4300"),
                advertised_best_ask=Decimal("0.4200"),
            ),
        ),
        dropped_count_before=3,
        dropped_count_after=3,
        elapsed_ms=7,
        details="continuation fingerprint did not match",
    )


def test_payload_serialization_is_canonical_exact_and_ordered() -> None:
    delta = BookDeltaPayload(
        changes=(
            BookChange(
                token_id="up-token",
                side=Side.BUY,
                price=Decimal("0.4200"),
                size=Decimal("0"),
                source_hash="first-hash",
                best_bid=Decimal("0"),
                best_ask=Decimal("0.4300"),
            ),
            BookChange(
                token_id="down-token",
                side=Side.SELL,
                price=Decimal("0.5800"),
                size=Decimal("4.500"),
                source_hash="second-hash",
                best_bid=Decimal("0.5700"),
                best_ask=Decimal("0.5900"),
            ),
        )
    )

    encoded = payload_json(delta)

    assert encoded == payload_json(delta)
    assert '"price":"0.4200"' in encoded
    assert encoded.index("first-hash") < encoded.index("second-hash")
    assert payload_kind(delta) is PayloadKind.BOOK_DELTA
    assert payload_from_json(PayloadKind.BOOK_DELTA, encoded) == delta


def test_capture_anomaly_serialization_is_canonical_and_exact() -> None:
    anomaly = _capture_anomaly()

    encoded = capture_anomaly_json(anomaly)

    assert encoded == capture_anomaly_json(anomaly)
    assert '"projected_best_bid":"0.4100"' in encoded
    assert '"price":"0.4200"' in encoded
    assert capture_anomaly_from_json(encoded) == anomaly


@pytest.mark.parametrize(
    "payload",
    [
        _metadata(),
        _baseline(),
        PublicTradePayload(
            token_id="up-token",
            price=Decimal("0.4250"),
            size=Decimal("2.750"),
            side=Side.BUY,
            fee_rate_bps=Decimal("100.00"),
            transaction_hash="0xtrade",
        ),
        TickSizeChangePayload(
            token_id="up-token",
            old_tick_size=Decimal("0.010"),
            new_tick_size=Decimal("0.0010"),
        ),
        ResolutionPayload(
            token_ids=("up-token", "down-token"),
            winning_token_id="up-token",
            winning_outcome="Up",
            source="market_websocket",
            resolution_id="resolution-1",
        ),
        CoverageGapPayload(
            reason=CoverageGapReason.SDK_QUEUE_DROP,
            started_at_ms=5_000,
            ended_at_ms=6_000,
            affected_condition_ids=("condition-1",),
            affected_market_slugs=("btc-updown-5m-1",),
            affected_token_ids=("up-token", "down-token"),
            details="one SDK event was dropped",
        ),
    ],
)
def test_every_payload_round_trips(payload) -> None:
    assert payload_from_json(payload_kind(payload), payload_json(payload)) == payload


def test_serialization_rejects_unknown_or_duplicate_fields() -> None:
    with pytest.raises(ValueError, match="fields are invalid"):
        payload_from_json(
            PayloadKind.BOOK_BASELINE,
            '{"asks":[],"bids":[],"source_hash":null,"token_id":"x","extra":1}',
        )
    with pytest.raises(ValueError, match="malformed"):
        payload_from_json(
            PayloadKind.BOOK_BASELINE,
            '{"asks":[],"asks":[],"bids":[],"source_hash":null,"token_id":"x"}',
        )


def test_create_refuses_overwrite_and_writer_lock_is_nonblocking(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    path = archive.path
    try:
        with pytest.raises(ArchiveExistsError):
            RecordingArchive.create(
                path,
                target_identity=archive.target_identity,
                started_at_ms=started_at_ms,
            )
        with pytest.raises(ArchiveLockedError):
            RecordingArchive.resume(
                path,
                target_identity=archive.target_identity,
                started_at_ms=started_at_ms,
            )
        assert archive._connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert archive._connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    finally:
        archive.close()


def test_archive_close_accepts_an_exact_historical_end(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    durable_boundary_ms = started_at_ms + 5
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=durable_boundary_ms,
            identity=_identity(),
        )
    )
    historical_end_ms = durable_boundary_ms + 10
    path = archive.path

    archive.close(ended_at_ms=historical_end_ms)

    with RecordingReader(path) as reader:
        session = reader.select_session()
    assert session.ended_at_ms == historical_end_ms
    assert session.clean_close is True
    assert session.integrity_status is SessionIntegrityStatus.COMPLETE


def test_archive_close_rejects_invalid_historical_ends(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    durable_boundary_ms = started_at_ms + 5
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=durable_boundary_ms,
            identity=_identity(),
        )
    )
    try:
        with pytest.raises(ValueError, match="archive end must be nonnegative"):
            archive.close(ended_at_ms=-1)
        with pytest.raises(ValueError, match="cannot precede its durable boundary"):
            archive.close(ended_at_ms=durable_boundary_ms - 1)

        assert archive.next_sequence == 2
    finally:
        archive.close(ended_at_ms=durable_boundary_ms)


def test_archive_close_without_an_end_keeps_wall_clock_behavior(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    wall_clock_end_ms = started_at_ms + 50
    monkeypatch.setattr(
        "polybot.recording.archive.writer.system_now_ms",
        lambda: wall_clock_end_ms,
    )
    path = archive.path

    archive.close()

    with RecordingReader(path) as reader:
        session = reader.select_session()
    assert session.ended_at_ms == wall_clock_end_ms


def test_replay_reader_holds_the_writer_lock_for_its_snapshot(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    path = archive.path
    target_identity = archive.target_identity
    archive.close()

    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        assert session.ended_at_ms is not None
        with pytest.raises(ArchiveLockedError):
            RecordingArchive.resume(
                path,
                target_identity=target_identity,
                started_at_ms=session.ended_at_ms + 1,
            )

    resumed = RecordingArchive.resume(
        path,
        target_identity=target_identity,
        started_at_ms=session.ended_at_ms + 1,
    )
    resumed.close()


def test_capture_anomaly_journal_is_non_replayable_and_filterable(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    starting_sequence = archive.next_sequence
    first = archive.append_capture_anomaly(
        _capture_anomaly(),
        observed_at_ms=started_at_ms + 1,
        identity=_identity(),
        subscription_generation=4,
    )
    second = archive.append_capture_anomaly(
        _capture_anomaly(failure_kind=CaptureFailureKind.SDK_HANDLE_DROP),
        observed_at_ms=started_at_ms + 2,
        identity=_identity(),
        subscription_generation=4,
    )
    assert archive.next_sequence == starting_sequence
    archive.close()

    with RecordingReader(archive.path) as reader:
        provenance = reader.capture_anomaly_journal_provenance
        assert reader.schema_version == SCHEMA_VERSION
        assert reader.has_capture_anomaly_journal
        assert provenance is not None
        assert provenance.available_from_session_id == 1
        assert reader.capture_anomaly_journal_available(1)
        assert tuple(reader.iter_events()) == ()
        assert reader.capture_anomalies() == (first, second)
        assert reader.capture_anomalies(
            failure_kind=CaptureFailureKind.SDK_HANDLE_DROP,
        ) == (second,)
        assert reader.capture_anomalies(
            end_at_ms=started_at_ms + 1,
            condition_id="condition-1",
            market_slug="btc-updown-5m-1",
        ) == (first,)


@pytest.mark.parametrize(
    ("column", "tampered_value"),
    [
        ("condition_id", "wrong-condition"),
        ("market_slug", "wrong-slug"),
        ("token_id", "down-token"),
    ],
)
def test_reader_rejects_tampered_capture_anomaly_identity_index(
    tmp_path,
    column: str,
    tampered_value: str,
) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_capture_anomaly(
        _capture_anomaly(),
        observed_at_ms=started_at_ms,
        identity=_identity(),
        subscription_generation=0,
    )
    path = archive.path
    archive.close()

    connection = sqlite3.connect(path)
    connection.execute(
        f"UPDATE capture_anomalies SET {column} = ? WHERE anomaly_id = 1",
        (tampered_value,),
    )
    connection.commit()
    connection.close()

    with RecordingReader(path) as reader:
        with pytest.raises(ArchiveFormatError, match="capture anomaly 1"):
            reader.capture_anomalies()


def test_reader_wraps_malformed_optional_diagnostic_tables(tmp_path) -> None:
    archive, _ = _opened_archive(tmp_path)
    path = archive.path
    archive.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "ALTER TABLE capture_anomalies RENAME COLUMN anomaly_id TO bad_id"
    )
    connection.commit()
    connection.close()

    with pytest.raises(ArchiveFormatError, match="capture anomaly journal"):
        RecordingReader(path)


def test_reader_wraps_malformed_diagnostic_provenance(tmp_path) -> None:
    archive, _ = _opened_archive(tmp_path)
    path = archive.path
    archive.close()

    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE recording_features")
    connection.execute(
        "CREATE TABLE recording_features (feature_name TEXT PRIMARY KEY) STRICT"
    )
    connection.execute(
        "INSERT INTO recording_features (feature_name) VALUES (?)",
        ("capture_anomaly_journal",),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ArchiveFormatError, match="provenance"):
        RecordingReader(path)


def test_async_writer_journals_anomaly_without_consuming_sequence(tmp_path) -> None:
    async def run() -> tuple[int, int]:
        archive, started_at_ms = _opened_archive(tmp_path)
        writer = AsyncRecordingWriter(archive)
        next_sequence = writer.next_sequence
        record = await writer.record_anomaly(
            _capture_anomaly(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
            subscription_generation=0,
        )
        await writer.stop(clean=True)
        return record.anomaly_id, next_sequence

    anomaly_id, next_sequence = asyncio.run(run())

    with RecordingReader(tmp_path / "capture.sqlite3") as reader:
        assert anomaly_id == 1
        assert reader.replay_cutoff_sequence == next_sequence - 1 == 0
        assert len(reader.capture_anomalies(session_id=1)) == 1


def test_resume_enables_anomaly_journal_only_for_new_legacy_sessions(
    tmp_path,
) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    path = archive.path
    target_identity = archive.target_identity
    archive.close()
    with RecordingReader(path) as reader:
        first_session = reader.sessions()[0]
        resume_at_ms = first_session.ended_at_ms + 1  # type: ignore[operator]

    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE capture_anomalies")
    connection.execute("DROP TABLE recording_features")
    connection.commit()
    connection.close()

    with RecordingReader(path) as reader:
        assert reader.schema_version == SCHEMA_VERSION
        assert not reader.has_capture_anomaly_journal
        assert not reader.capture_anomaly_journal_available(1)
        with pytest.raises(CaptureAnomalyJournalUnavailableError):
            reader.capture_anomalies(session_id=1)

    resumed = RecordingArchive.resume(
        path,
        target_identity=target_identity,
        started_at_ms=resume_at_ms,
    )
    assert resumed.next_sequence == 2
    resumed.close()

    with RecordingReader(path) as reader:
        provenance = reader.capture_anomaly_journal_provenance
        assert provenance is not None
        assert provenance.available_from_session_id == 2
        assert [event.sequence for event in reader.iter_events()] == [1]
        assert not reader.capture_anomaly_journal_available(1)
        assert reader.capture_anomaly_journal_available(2)
        assert reader.capture_anomalies(session_id=2) == ()
        with pytest.raises(CaptureAnomalyJournalUnavailableError, match="sessions: 1"):
            reader.capture_anomalies(session_id=1)
        with pytest.raises(CaptureAnomalyJournalUnavailableError, match="sessions: 1"):
            reader.capture_anomalies()


def test_archive_requires_metadata_baselines_and_global_sequence(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    try:
        with pytest.raises(ArchiveIntegrityError, match="metadata"):
            archive.append_event(
                _event(
                    archive,
                    _baseline(),
                    observed_at_ms=started_at_ms,
                    identity=_identity("up-token"),
                )
            )

        archive.append_metadata(
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
            )
        )
        delta = BookDeltaPayload(
            changes=(
                BookChange(
                    token_id="up-token",
                    side=Side.BUY,
                    price=Decimal("0.4200"),
                    size=Decimal("0"),
                ),
            )
        )
        with pytest.raises(ArchiveIntegrityError, match="missing a baseline"):
            archive.append_event(
                _event(
                    archive,
                    delta,
                    observed_at_ms=started_at_ms + 1,
                    identity=_identity("up-token"),
                )
            )

        archive.append_event(
            _event(
                archive,
                _baseline(),
                observed_at_ms=started_at_ms + 1,
                identity=_identity("up-token"),
            )
        )
        wrong_sequence = replace(
            _event(
                archive,
                delta,
                observed_at_ms=started_at_ms + 2,
                identity=_identity("up-token"),
            ),
            sequence=archive.next_sequence + 1,
        )
        with pytest.raises(ArchiveIntegrityError, match="expected recording sequence"):
            archive.append_event(wrong_sequence)
    finally:
        archive.close()


def test_archive_rejects_payload_identity_outside_committed_market(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    try:
        archive.append_metadata(
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
            )
        )
        with pytest.raises(ArchiveIntegrityError, match="token identity"):
            archive.append_event(
                _event(
                    archive,
                    BookBaselinePayload(
                        token_id="outsider-token",
                        bids=(),
                        asks=(),
                    ),
                    observed_at_ms=started_at_ms + 1,
                    identity=MarketIdentity(
                        condition_id="condition-1",
                        market_slug="btc-updown-5m-1",
                        token_id="outsider-token",
                    ),
                )
            )
        with pytest.raises(ArchiveIntegrityError, match="event identity"):
            archive.append_event(
                _event(
                    archive,
                    PublicTradePayload(
                        token_id="up-token",
                        price=Decimal("0.42"),
                        size=Decimal("1"),
                        side=Side.BUY,
                    ),
                    observed_at_ms=started_at_ms + 1,
                    identity=MarketIdentity(
                        condition_id="condition-1",
                        market_slug="wrong-slug",
                        token_id="up-token",
                    ),
                )
            )
        with pytest.raises(ArchiveIntegrityError, match="resolution outcome"):
            archive.append_event(
                _event(
                    archive,
                    ResolutionPayload(
                        token_ids=("up-token", "down-token"),
                        winning_token_id="up-token",
                        winning_outcome="Down",
                        source="market_websocket",
                    ),
                    observed_at_ms=started_at_ms + 1,
                    identity=_identity(),
                )
            )
    finally:
        archive.close()


def test_reader_reconstructs_events_metadata_and_checkpoint(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_events(
        (
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
                source_timestamp_ms=started_at_ms - 10,
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 1,
                session_id=archive.session_id,
                subscription_generation=0,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=started_at_ms - 9,
                identity=_identity("up-token"),
                payload=_baseline(),
            ),
        )
    )
    delta = BookDeltaPayload(
        changes=(
            BookChange(
                "up-token",
                Side.BUY,
                Decimal("0.4200"),
                Decimal("0"),
            ),
        )
    )
    archive.append_event(
        _event(
            archive,
            delta,
            observed_at_ms=started_at_ms + 2,
            identity=_identity("up-token"),
        )
    )
    sequence = archive.next_sequence - 1
    archive.append_checkpoint(
        BookCheckpoint(
            sequence=sequence,
            session_id=archive.session_id,
            subscription_generation=0,
            observed_at_ms=started_at_ms + 2,
            identity=_identity("up-token"),
            book=_baseline(),
        )
    )
    archive.append_checkpoint(
        BookCheckpoint(
            sequence=sequence,
            session_id=archive.session_id,
            subscription_generation=0,
            observed_at_ms=started_at_ms + 62_000,
            identity=_identity("up-token"),
            book=_baseline(),
        )
    )
    assert archive.next_sequence == 4
    archive.close()

    with RecordingReader(archive.path) as reader:
        events = tuple(reader.iter_events(token_id="up-token"))
        assert [event.sequence for event in events] == [1, 2, 3]
        assert events[0].source_timestamp_ms == started_at_ms - 10
        assert reader.market_at("condition-1", started_at_ms + 2) == _metadata()
        checkpoint = reader.checkpoint_before("up-token", started_at_ms + 62_001)
        assert checkpoint is not None
        assert checkpoint.sequence == 3
        assert checkpoint.observed_at_ms == started_at_ms + 62_000
        assert checkpoint.book == _baseline()
        assert reader.last_observed_at_ms == started_at_ms + 62_000
        assert reader.unresolved_markets() == (_metadata(),)


def test_common_checkpoint_batch_is_all_or_nothing(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_events(
        (
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
                generation=1,
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 1,
                session_id=archive.session_id,
                subscription_generation=1,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=None,
                identity=_identity("up-token"),
                payload=_baseline("up-token"),
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 2,
                session_id=archive.session_id,
                subscription_generation=1,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=None,
                identity=_identity("down-token"),
                payload=_baseline("down-token"),
            ),
        )
    )
    sequence = archive.next_sequence - 1
    up = BookCheckpoint(
        sequence=sequence,
        session_id=archive.session_id,
        subscription_generation=1,
        observed_at_ms=started_at_ms + 2,
        identity=_identity("up-token"),
        book=_baseline("up-token"),
    )
    wrong_session = BookCheckpoint(
        sequence=sequence,
        session_id=archive.session_id + 1,
        subscription_generation=1,
        observed_at_ms=started_at_ms + 2,
        identity=_identity("down-token"),
        book=_baseline("down-token"),
    )

    with pytest.raises(ArchiveIntegrityError, match="different recording session"):
        archive.append_checkpoints((up, wrong_session))

    count = archive._connection.execute(
        "SELECT COUNT(*) FROM book_checkpoints"
    ).fetchone()[0]
    assert count == 0
    archive.close()


def test_metadata_and_resolution_batch_is_all_or_nothing(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    metadata = _event(
        archive,
        _metadata(),
        observed_at_ms=started_at_ms,
        identity=_identity(),
    )
    invalid_resolution = RecordedEvent(
        sequence=archive.next_sequence + 1,
        session_id=archive.session_id,
        subscription_generation=0,
        observed_at_ms=started_at_ms,
        source_timestamp_ms=None,
        identity=_identity(),
        payload=ResolutionPayload(
            token_ids=("up-token", "down-token"),
            winning_token_id="up-token",
            winning_outcome="Down",
            source="gamma_reconciliation",
        ),
    )

    with pytest.raises(ArchiveIntegrityError, match="resolution outcome"):
        archive.append_events((metadata, invalid_resolution))

    event_count = archive._connection.execute(
        "SELECT COUNT(*) FROM events"
    ).fetchone()[0]
    metadata_count = archive._connection.execute(
        "SELECT COUNT(*) FROM metadata_revisions"
    ).fetchone()[0]
    assert event_count == 0
    assert metadata_count == 0
    assert archive.next_sequence == 1
    archive.close()


def test_reader_checkpoint_and_events_rebuild_point_in_time_book(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_events(
        (
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 1,
                session_id=archive.session_id,
                subscription_generation=1,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=started_at_ms,
                identity=_identity("up-token"),
                payload=_baseline(),
            ),
        )
    )
    archive.append_checkpoint(
        BookCheckpoint(
            sequence=archive.next_sequence - 1,
            session_id=archive.session_id,
            subscription_generation=1,
            observed_at_ms=started_at_ms + 1,
            identity=_identity("up-token"),
            book=_baseline(),
        )
    )
    for offset, size in ((2, Decimal("5")), (3, Decimal("0"))):
        archive.append_event(
            _event(
                archive,
                BookDeltaPayload(
                    changes=(
                        BookChange(
                            "up-token",
                            Side.BUY,
                            Decimal("0.42" if offset == 2 else "0.41"),
                            size,
                        ),
                    )
                ),
                observed_at_ms=started_at_ms + offset,
                identity=_identity("up-token"),
                generation=1,
            )
        )
    target_at_ms = started_at_ms + 3
    path = archive.path
    archive.close()

    market = Market(
        condition_id="condition-1",
        slug="btc-updown-5m-1",
        question="Will BTC go up?",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("5"),
        neg_risk=False,
        fee_rate=Decimal("0.25"),
        outcomes=(
            MarketOutcome("Up", "up-token"),
            MarketOutcome("Down", "down-token"),
        ),
    )
    projector = BookDepthProjector((market,))
    snapshots = []
    with RecordingReader(path) as reader:
        checkpoint = reader.checkpoint_before("up-token", target_at_ms)
        assert checkpoint is not None
        projector.apply_baseline(
            checkpoint.book,
            condition_id="condition-1",
            received_at_ms=checkpoint.observed_at_ms,
        )
        for event in reader.iter_events(
            start_at_ms=checkpoint.observed_at_ms,
            end_at_ms=target_at_ms,
            token_id="up-token",
        ):
            if event.sequence <= checkpoint.sequence:
                continue
            if isinstance(event.payload, BookBaselinePayload):
                snapshots.append(
                    projector.apply_baseline(
                        event.payload,
                        condition_id="condition-1",
                        received_at_ms=event.observed_at_ms,
                    )
                )
            elif isinstance(event.payload, BookDeltaPayload):
                snapshots.extend(
                    projector.apply_delta(
                        event.payload,
                        condition_id="condition-1",
                        received_at_ms=event.observed_at_ms,
                    )
                )

    assert [snapshot.received_at_ms for snapshot in snapshots] == [
        started_at_ms + 2,
        started_at_ms + 3,
    ]
    assert tuple((level.price, level.size) for level in snapshots[0].bids) == (
        (Decimal("0.42"), Decimal("5")),
        (Decimal("0.41"), Decimal("7.0")),
    )
    assert tuple((level.price, level.size) for level in snapshots[1].bids) == (
        (Decimal("0.42"), Decimal("5")),
    )


def test_gap_lifecycle_rejects_ranges_and_requires_fresh_baseline(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_events(
        (
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 1,
                session_id=archive.session_id,
                subscription_generation=0,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=None,
                identity=_identity("up-token"),
                payload=_baseline(),
            ),
        )
    )
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.SDK_QUEUE_DROP,
                started_at_ms=started_at_ms + 2,
                ended_at_ms=None,
                affected_condition_ids=("condition-1",),
                affected_market_slugs=("btc-updown-5m-1",),
                affected_token_ids=("up-token",),
            ),
            observed_at_ms=started_at_ms + 2,
            identity=_identity(),
        )
    )
    delta = BookDeltaPayload(
        changes=(
            BookChange("up-token", Side.BUY, Decimal("0.42"), Decimal("0")),
        )
    )
    with pytest.raises(ArchiveIntegrityError, match="missing a baseline"):
        archive.append_event(
            _event(
                archive,
                delta,
                observed_at_ms=started_at_ms + 3,
                identity=_identity("up-token"),
            )
        )
    archive.append_event(
        _event(
            archive,
            _baseline(),
            observed_at_ms=started_at_ms + 4,
            identity=_identity("up-token"),
        )
    )
    archive.close_gap(gap_id, ended_at_ms=started_at_ms + 4)
    archive.close()

    with RecordingReader(archive.path) as reader:
        gaps = reader.coverage_gaps(condition_id="condition-1")
        assert len(gaps) == 1
        assert gaps[0].gap.ended_at_ms == started_at_ms + 4
        assert not gaps[0].is_open
        with pytest.raises(ArchiveCoverageError):
            tuple(reader.iter_events(condition_id="condition-1"))
        assert len(
            tuple(reader.iter_events(condition_id="condition-1", allow_gaps=True))
        ) == 4
        assert reader.sessions()[0].clean_close
        assert (
            reader.sessions()[0].integrity_status
            is SessionIntegrityStatus.INCOMPLETE
        )


def test_large_coverage_gap_errors_compact_contiguous_ids(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    for offset in range(25):
        archive.append_gap(
            _event(
                archive,
                CoverageGapPayload(
                    reason=CoverageGapReason.SDK_HANDLE_DROP,
                    started_at_ms=started_at_ms + offset,
                    ended_at_ms=None,
                    affected_condition_ids=("condition-1",),
                ),
                observed_at_ms=started_at_ms + offset,
                identity=_identity(),
            )
        )
    archive.close()

    with RecordingReader(archive.path) as reader:
        with pytest.raises(
            ArchiveCoverageError,
            match=r"25 gaps \(IDs 1-25\)$",
        ):
            tuple(reader.iter_events(condition_id="condition-1"))


def test_reader_rejects_a_delta_without_a_post_gap_baseline(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_events(
        (
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 1,
                session_id=archive.session_id,
                subscription_generation=0,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=None,
                identity=_identity("up-token"),
                payload=_baseline(),
            ),
        )
    )
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.SDK_QUEUE_DROP,
                started_at_ms=started_at_ms + 2,
                ended_at_ms=None,
                affected_token_ids=("up-token",),
            ),
            observed_at_ms=started_at_ms + 2,
            identity=_identity("up-token"),
        )
    )
    archive.append_event(
        _event(
            archive,
            _baseline(),
            observed_at_ms=started_at_ms + 3,
            identity=_identity("up-token"),
        )
    )
    replacement_baseline_sequence = archive.next_sequence - 1
    archive.append_event(
        _event(
            archive,
            BookDeltaPayload(
                changes=(
                    BookChange(
                        "up-token",
                        Side.BUY,
                        Decimal("0.42"),
                        Decimal("0"),
                    ),
                )
            ),
            observed_at_ms=started_at_ms + 4,
            identity=_identity("up-token"),
        )
    )
    archive.close_gap(gap_id, ended_at_ms=started_at_ms + 3)
    path = archive.path
    archive.close()

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "DELETE FROM events WHERE sequence = ?",
        (replacement_baseline_sequence,),
    )
    connection.commit()
    connection.close()

    with RecordingReader(path) as reader:
        with pytest.raises(ArchiveIntegrityError, match="no preceding baseline"):
            tuple(reader.iter_events(allow_gaps=True))


def test_event_iteration_and_gap_check_share_one_snapshot(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    reader = RecordingReader(archive.path)
    try:
        events = reader.iter_events()
        archive.append_gap(
            _event(
                archive,
                CoverageGapPayload(
                    reason=CoverageGapReason.SDK_QUEUE_DROP,
                    started_at_ms=started_at_ms + 1,
                    ended_at_ms=None,
                    affected_condition_ids=("condition-1",),
                ),
                observed_at_ms=started_at_ms + 1,
                identity=_identity(),
            )
        )

        assert [event.sequence for event in events] == [1]
    finally:
        reader.close()
        archive.close()


def test_global_gap_can_cover_an_unresolved_dynamic_slug(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.CURRENT_SLUG_UNAVAILABLE,
                started_at_ms=started_at_ms,
                ended_at_ms=None,
                affected_market_slugs=("btc-updown-5m-next",),
            ),
            observed_at_ms=started_at_ms,
            identity=MarketIdentity(market_slug="btc-updown-5m-next"),
        )
    )
    archive.close()

    with RecordingReader(archive.path) as reader:
        gaps = reader.coverage_gaps(
            market_slug="btc-updown-5m-next",
            open_only=True,
        )
        assert [gap.gap_id for gap in gaps] == [gap_id]
        assert reader.coverage_gaps(market_slug="different") == ()


def test_resume_validates_identity_continues_sequence_and_adds_session(
    tmp_path,
) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    path = archive.path
    target_identity = archive.target_identity
    archive.close()
    with RecordingReader(path) as reader:
        first_session = reader.sessions()[0]
        assert first_session.recorder_version
        assert first_session.sdk_version
        resume_at_ms = first_session.ended_at_ms + 1  # type: ignore[operator]

    with pytest.raises(ArchiveFormatError, match="target identity"):
        RecordingArchive.resume(
            path,
            target_identity="different-target",
            started_at_ms=resume_at_ms,
        )

    resumed = RecordingArchive.resume(
        path,
        target_identity=target_identity,
        started_at_ms=resume_at_ms,
    )
    assert resumed.session_id == 2
    assert resumed.next_sequence == 2
    assert resumed.resume_from_ms == resume_at_ms - 1
    resumed.close()

    with RecordingReader(path) as reader:
        assert len(reader.sessions()) == 2
        assert reader.sessions()[1].integrity_status is SessionIntegrityStatus.COMPLETE


def test_reader_rejects_unsupported_schema_and_malformed_payload(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    path = archive.path
    archive.close()

    connection = sqlite3.connect(path)
    connection.execute("UPDATE events SET payload_json = '{}' WHERE sequence = 1")
    connection.commit()
    connection.close()
    with RecordingReader(path) as reader:
        with pytest.raises(ArchiveFormatError, match="event 1"):
            tuple(reader.iter_events())

    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(ArchiveFormatError, match="unsupported"):
        RecordingReader(path)


def test_reader_rejects_a_missing_core_schema_table(tmp_path) -> None:
    archive, _ = _opened_archive(tmp_path)
    path = archive.path
    archive.close()
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE events")
    connection.commit()
    connection.close()

    with pytest.raises(ArchiveFormatError, match="core table is malformed: events"):
        RecordingReader(path)


def test_reader_detects_delta_without_a_preceding_baseline(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_events(
        (
            _event(
                archive,
                _metadata(),
                observed_at_ms=started_at_ms,
                identity=_identity(),
            ),
            RecordedEvent(
                sequence=archive.next_sequence + 1,
                session_id=archive.session_id,
                subscription_generation=0,
                observed_at_ms=started_at_ms + 1,
                source_timestamp_ms=None,
                identity=_identity("up-token"),
                payload=_baseline(),
            ),
        )
    )
    archive.append_event(
        _event(
            archive,
            BookDeltaPayload(
                changes=(
                    BookChange(
                        "up-token",
                        Side.BUY,
                        Decimal("0.42"),
                        Decimal("0"),
                    ),
                )
            ),
            observed_at_ms=started_at_ms + 2,
            identity=_identity("up-token"),
        )
    )
    path = archive.path
    archive.close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("DELETE FROM event_tokens WHERE sequence = 2")
    connection.execute("DELETE FROM events WHERE sequence = 2")
    connection.commit()
    connection.close()

    with RecordingReader(path) as reader:
        with pytest.raises(ArchiveIntegrityError, match="no preceding baseline"):
            tuple(reader.iter_events())


def test_resolution_removes_market_from_resume_set(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    archive.append_event(
        _event(
            archive,
            ResolutionPayload(
                token_ids=("up-token", "down-token"),
                winning_token_id="up-token",
                winning_outcome="Up",
                source="gamma_reconciliation",
            ),
            observed_at_ms=started_at_ms + 1,
            identity=_identity(),
        )
    )
    archive.close()

    with RecordingReader(archive.path) as reader:
        assert reader.unresolved_markets() == ()
        assert reader.unresolved_markets(at_ms=started_at_ms) == (_metadata(),)
        resolved_market = reader.market_at("condition-1", started_at_ms + 1)
        assert resolved_market is not None
        assert resolved_market.resolved
        assert resolved_market.winning_token_id == "up-token"
        assert resolved_market.winning_outcome == "Up"
        assert resolved_market.resolution_source == "https://example.test/rules"


def test_reader_rejects_stored_slug_mismatch_against_metadata(tmp_path) -> None:
    archive, started_at_ms = _opened_archive(tmp_path)
    archive.append_metadata(
        _event(
            archive,
            _metadata(),
            observed_at_ms=started_at_ms,
            identity=_identity(),
        )
    )
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id="up-token",
                price=Decimal("0.42"),
                size=Decimal("1"),
                side=Side.BUY,
            ),
            observed_at_ms=started_at_ms + 1,
            identity=_identity("up-token"),
        )
    )
    path = archive.path
    archive.close()
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE events SET market_slug = 'wrong-slug' WHERE sequence = 2"
    )
    connection.commit()
    connection.close()

    with RecordingReader(path) as reader:
        with pytest.raises(ArchiveIntegrityError, match="event identity"):
            tuple(reader.iter_events())
