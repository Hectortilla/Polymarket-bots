from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from decimal import Decimal

import pytest

from polybot.framework.events import Side
from polybot.polymarket.book_projector import BookDepthProjector
from polybot.polymarket.types import Market, MarketOutcome
from polybot.recording.archive import (
    SCHEMA_VERSION,
    ArchiveCoverageError,
    ArchiveExistsError,
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
    RecordingArchive,
    RecordingReader,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookChange,
    BookCheckpoint,
    BookDeltaPayload,
    CoverageGapPayload,
    FeeScheduleMetadata,
    MarketEventMetadata,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    PublicTradePayload,
    RecordedBookLevel,
    RecordedEvent,
    ResolutionPayload,
    SessionIntegrityStatus,
    TickSizeChangePayload,
)
from polybot.recording.serialization import (
    PayloadKind,
    payload_from_json,
    payload_json,
    payload_kind,
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
            reason="sdk_queue_drop",
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
                reason="sdk_queue_drop",
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
                reason="sdk_queue_drop",
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
                    reason="sdk_queue_drop",
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
                reason="current_slug_unavailable",
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
