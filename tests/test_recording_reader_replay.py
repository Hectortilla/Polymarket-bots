from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import polybot.recording.archive as archive_module
from polybot.recording.archive import (
    ArchiveCoverageError,
    ArchiveFormatError,
    RecordingArchive,
    RecordingEventBounds,
    RecordingReader,
)
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
    TickSizeChangePayload,
)


def _market(
    condition_id: str,
    market_slug: str,
    token_prefix: str,
) -> MarketMetadataPayload:
    return MarketMetadataPayload(
        market_id=f"market-{condition_id}",
        condition_id=condition_id,
        market_slug=market_slug,
        question=f"Question for {condition_id}",
        events=(),
        outcomes=(
            MarketOutcomeMetadata("Up", f"{token_prefix}-up"),
            MarketOutcomeMetadata("Down", f"{token_prefix}-down"),
        ),
        active=True,
        closed=False,
        archived=False,
        start_at_ms=None,
        end_at_ms=None,
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


def _identity(
    market: MarketMetadataPayload,
    token_id: str | None = None,
) -> MarketIdentity:
    return MarketIdentity(
        condition_id=market.condition_id,
        market_slug=market.market_slug,
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
    generation: int = 1,
) -> RecordedEvent:
    return RecordedEvent(
        sequence=archive.next_sequence,
        session_id=archive.session_id,
        subscription_generation=generation,
        observed_at_ms=observed_at_ms,
        source_timestamp_ms=None,
        identity=identity,
        payload=payload,  # type: ignore[arg-type]
    )


def _append_market(
    archive: RecordingArchive,
    market: MarketMetadataPayload,
    *,
    observed_at_ms: int,
    generation: int = 1,
) -> int:
    archive.append_metadata(
        _event(
            archive,
            market,
            observed_at_ms=observed_at_ms,
            identity=_identity(market),
            generation=generation,
        )
    )
    for offset, outcome in enumerate(market.outcomes, start=1):
        archive.append_event(
            _event(
                archive,
                _book(outcome.token_id),
                observed_at_ms=observed_at_ms + offset,
                identity=_identity(market, outcome.token_id),
                generation=generation,
            )
        )
    return observed_at_ms + len(market.outcomes)


def _checkpoint(
    archive: RecordingArchive,
    market: MarketMetadataPayload,
    token_id: str,
    *,
    sequence: int,
    observed_at_ms: int,
    generation: int = 1,
) -> BookCheckpoint:
    return BookCheckpoint(
        sequence=sequence,
        session_id=archive.session_id,
        subscription_generation=generation,
        observed_at_ms=observed_at_ms,
        identity=_identity(market, token_id),
        book=_book(token_id),
    )


def test_replay_lease_reuses_its_validated_archive_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "single-validation.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity="slugs:market-one",
        started_at_ms=1_000,
    )
    _append_market(
        archive,
        _market("condition-1", "market-one", "one"),
        observed_at_ms=1_000,
    )
    archive.close(ended_at_ms=1_010)

    original_validate = archive_module._validate_archive
    validation_count = 0

    def count_validation(connection: sqlite3.Connection) -> str:
        nonlocal validation_count
        validation_count += 1
        return original_validate(connection)

    monkeypatch.setattr(archive_module, "_validate_archive", count_validation)

    with RecordingReader.for_replay(path) as reader:
        assert reader.target_identity == "slugs:market-one"

    assert validation_count == 1


def test_market_state_orders_tick_changes_with_metadata_revisions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "market-state.sqlite3"
    market = _market("condition-1", "market-one", "one")
    archive = RecordingArchive.create(
        path,
        target_identity="slugs:market-one",
        started_at_ms=1_000,
    )
    archive.append_metadata(
        _event(
            archive,
            market,
            observed_at_ms=1_000,
            identity=_identity(market),
        )
    )
    archive.append_event(
        _event(
            archive,
            TickSizeChangePayload(
                token_id=market.outcomes[0].token_id,
                old_tick_size=Decimal("0.01"),
                new_tick_size=Decimal("0.02"),
            ),
            observed_at_ms=1_001,
            identity=_identity(market, market.outcomes[0].token_id),
        )
    )
    archive.append_metadata(
        _event(
            archive,
            replace(market, minimum_tick_size=Decimal("0.01")),
            observed_at_ms=1_002,
            identity=_identity(market),
        )
    )
    archive.close(ended_at_ms=1_010)

    with RecordingReader.for_replay(path) as reader:
        after_tick = reader.market_state_at(market.condition_id, 1_001)
        after_revision = reader.market_state_at(market.condition_id, 1_002)
        before_revision_sequence = reader.market_state_at(
            market.condition_id,
            1_002,
            sequence_cutoff=2,
        )

    assert after_tick is not None
    assert after_tick.minimum_tick_size == Decimal("0.02")
    assert after_revision is not None
    assert after_revision.minimum_tick_size == Decimal("0.01")
    assert before_revision_sequence is not None
    assert before_revision_sequence.minimum_tick_size == Decimal("0.02")


def test_reader_session_selection_market_enumeration_and_cutoff(tmp_path) -> None:
    path = tmp_path / "sessions.sqlite3"
    started_at_ms = time.time_ns() // 1_000_000
    first_market = _market("condition-1", "market-one", "one")
    second_market = _market("condition-2", "market-two", "two")
    archive = RecordingArchive.create(
        path,
        target_identity="bot:example:create",
        started_at_ms=started_at_ms,
    )
    _append_market(archive, first_market, observed_at_ms=started_at_ms)
    archive.close()

    frozen_reader = RecordingReader(path)
    first_session = frozen_reader.select_session()
    assert first_session.session_id == 1
    assert frozen_reader.replay_cutoff_sequence == 3
    assert frozen_reader.event_bounds() == RecordingEventBounds(
        first_sequence=1,
        last_sequence=3,
        start_at_ms=started_at_ms,
        end_at_ms=started_at_ms + 2,
    )

    assert first_session.ended_at_ms is not None
    resume_at_ms = first_session.ended_at_ms + 1
    resumed = RecordingArchive.resume(
        path,
        target_identity="bot:example:create",
        started_at_ms=resume_at_ms,
    )
    for offset, outcome in enumerate(first_market.outcomes):
        resumed.append_event(
            _event(
                resumed,
                _book(outcome.token_id),
                observed_at_ms=resume_at_ms + offset,
                identity=_identity(first_market, outcome.token_id),
                generation=2,
            )
        )
    second_market_at_ms = resume_at_ms + 2
    _append_market(
        resumed,
        second_market,
        observed_at_ms=second_market_at_ms,
        generation=3,
    )
    resumed.close()

    try:
        assert [event.sequence for event in frozen_reader.iter_events()] == [1, 2, 3]
        assert frozen_reader.sessions() == (first_session,)
        assert frozen_reader.markets_at(resume_at_ms + 4) == (first_market,)
    finally:
        frozen_reader.close()

    with RecordingReader(path) as reader:
        with pytest.raises(ArchiveFormatError, match="explicit session ID"):
            reader.select_session()
        assert reader.select_session(2).session_id == 2
        with pytest.raises(ArchiveFormatError, match="does not exist"):
            reader.select_session(3)

        before_dynamic_market = reader.markets_at(
            resume_at_ms + 1,
            session_id=2,
        )
        assert before_dynamic_market == (first_market,)
        assert reader.markets_at(
            second_market_at_ms + 2,
            session_id=2,
            market_slugs={"market-two"},
        ) == (second_market,)
        second_bounds = reader.event_bounds(session_id=2)
        assert second_bounds is not None
        assert (second_bounds.first_sequence, second_bounds.last_sequence) == (4, 8)


def test_reader_set_filters_scope_events_and_coverage_gaps(tmp_path) -> None:
    path = tmp_path / "sets.sqlite3"
    started_at_ms = time.time_ns() // 1_000_000
    first_market = _market("condition-1", "market-one", "one")
    second_market = _market("condition-2", "market-two", "two")
    archive = RecordingArchive.create(
        path,
        target_identity="slugs:market-one,market-two",
        started_at_ms=started_at_ms,
    )
    first_end = _append_market(
        archive,
        first_market,
        observed_at_ms=started_at_ms,
    )
    second_start = first_end + 1
    second_end = _append_market(
        archive,
        second_market,
        observed_at_ms=second_start,
        generation=2,
    )
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.SDK_QUEUE_DROP,
                started_at_ms=second_end + 1,
                ended_at_ms=None,
                affected_condition_ids=(second_market.condition_id,),
                affected_market_slugs=(second_market.market_slug,),
                affected_token_ids=tuple(
                    outcome.token_id for outcome in second_market.outcomes
                ),
            ),
            observed_at_ms=second_end + 1,
            identity=_identity(second_market),
            generation=2,
        )
    )
    for offset, outcome in enumerate(second_market.outcomes, start=2):
        archive.append_event(
            _event(
                archive,
                _book(outcome.token_id),
                observed_at_ms=second_end + offset,
                identity=_identity(second_market, outcome.token_id),
                generation=2,
            )
        )
    archive.close_gap(gap_id, ended_at_ms=second_end + 3)
    archive.close()

    with RecordingReader(path) as reader:
        first_events = tuple(
            reader.iter_events(
                session_id=1,
                condition_ids={first_market.condition_id},
            )
        )
        assert [event.sequence for event in first_events] == [1, 2, 3]
        assert [
            event.sequence
            for event in reader.iter_events(market_slugs={first_market.market_slug})
        ] == [1, 2, 3]
        assert reader.coverage_gaps(
            condition_ids={first_market.condition_id}
        ) == ()
        assert reader.event_count(
            condition_ids={first_market.condition_id}
        ) == 3
        assert [
            gap.gap_id
            for gap in reader.coverage_gaps(
                market_slugs={second_market.market_slug}
            )
        ] == [gap_id]
        assert reader.event_count(
            market_slugs={second_market.market_slug},
            allow_gaps=True,
        ) == 5
        with pytest.raises(ArchiveCoverageError):
            tuple(
                reader.iter_events(
                    condition_ids={
                        first_market.condition_id,
                        second_market.condition_id,
                    }
                )
            )
        with pytest.raises(ArchiveCoverageError):
            reader.event_count(market_slugs={second_market.market_slug})
        with pytest.raises(ValueError, match="either condition ID or condition IDs"):
            tuple(
                reader.iter_events(
                    condition_id=first_market.condition_id,
                    condition_ids={first_market.condition_id},
                )
            )


def test_complete_baseline_pair_requires_both_tokens_in_one_generation(
    tmp_path,
) -> None:
    path = tmp_path / "baseline-pair.sqlite3"
    started_at_ms = time.time_ns() // 1_000_000
    market = _market("condition-1", "market-one", "one")
    first_token, second_token = (
        outcome.token_id for outcome in market.outcomes
    )
    archive = RecordingArchive.create(
        path,
        target_identity="slugs:market-one",
        started_at_ms=started_at_ms,
    )
    archive.append_metadata(
        _event(
            archive,
            market,
            observed_at_ms=started_at_ms,
            identity=_identity(market),
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(first_token),
            observed_at_ms=started_at_ms + 1,
            identity=_identity(market, first_token),
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(second_token),
            observed_at_ms=started_at_ms + 2,
            identity=_identity(market, second_token),
            generation=2,
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(first_token),
            observed_at_ms=started_at_ms + 3,
            identity=_identity(market, first_token),
            generation=2,
        )
    )
    archive.close()

    with RecordingReader(path) as reader:
        assert not reader.has_complete_baseline_pair(
            market,
            start_at_ms=started_at_ms,
            end_at_ms=started_at_ms + 2,
            session_id=1,
        )
        assert reader.has_complete_baseline_pair(
            market,
            start_at_ms=started_at_ms + 2,
            end_at_ms=started_at_ms + 3,
            session_id=1,
        )


def test_checkpoint_pair_requires_one_common_gap_free_boundary(tmp_path) -> None:
    path = tmp_path / "checkpoints.sqlite3"
    started_at_ms = time.time_ns() // 1_000_000
    market = _market("condition-1", "market-one", "one")
    archive = RecordingArchive.create(
        path,
        target_identity="slugs:market-one",
        started_at_ms=started_at_ms,
    )
    baseline_end = _append_market(
        archive,
        market,
        observed_at_ms=started_at_ms,
    )
    first_token, second_token = (
        outcome.token_id for outcome in market.outcomes
    )
    archive.append_checkpoints(
        (
            _checkpoint(
                archive,
                market,
                first_token,
                sequence=2,
                observed_at_ms=baseline_end + 1,
            ),
            _checkpoint(
                archive,
                market,
                second_token,
                sequence=3,
                observed_at_ms=baseline_end + 1,
            ),
        )
    )
    common_at_ms = baseline_end + 2
    archive.append_checkpoints(
        tuple(
            _checkpoint(
                archive,
                market,
                token_id,
                sequence=3,
                observed_at_ms=common_at_ms,
            )
            for token_id in (first_token, second_token)
        )
    )
    archive.append_checkpoint(
        _checkpoint(
            archive,
            market,
            first_token,
            sequence=3,
            observed_at_ms=common_at_ms + 1,
        )
    )
    gap_start = common_at_ms + 2
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=gap_start,
                ended_at_ms=None,
                affected_condition_ids=(market.condition_id,),
                affected_market_slugs=(market.market_slug,),
                affected_token_ids=(first_token, second_token),
            ),
            observed_at_ms=gap_start,
            identity=_identity(market),
        )
    )
    for offset, token_id in enumerate((first_token, second_token), start=1):
        archive.append_event(
            _event(
                archive,
                _book(token_id),
                observed_at_ms=gap_start + offset,
                identity=_identity(market, token_id),
            )
        )
    gap_end = gap_start + 2
    archive.close_gap(gap_id, ended_at_ms=gap_end)
    recovered_at_ms = gap_end + 1
    archive.append_checkpoints(
        tuple(
            _checkpoint(
                archive,
                market,
                token_id,
                sequence=archive.next_sequence - 1,
                observed_at_ms=recovered_at_ms,
            )
            for token_id in (first_token, second_token)
        )
    )
    archive.close()

    with RecordingReader(path) as reader:
        assert reader.checkpoint_pair_before(
            market.condition_id,
            baseline_end + 1,
        ) is None
        pair = reader.checkpoint_pair_before(
            market.condition_id,
            common_at_ms + 1,
        )
        assert pair is not None
        assert tuple(checkpoint.book.token_id for checkpoint in pair) == (
            first_token,
            second_token,
        )
        assert {checkpoint.sequence for checkpoint in pair} == {3}
        assert {checkpoint.observed_at_ms for checkpoint in pair} == {common_at_ms}
        assert reader.checkpoint_pair_at(
            market.condition_id,
            common_at_ms,
        ) == pair
        assert reader.checkpoint_pair_at(
            market.condition_id,
            common_at_ms + 1,
        ) is None
        with pytest.raises(ArchiveCoverageError):
            reader.checkpoint_pair_before(
                market.condition_id,
                gap_end,
            )
        recovered_pair = reader.checkpoint_pair_before(
            market.condition_id,
            recovered_at_ms,
            session_id=1,
        )
        assert recovered_pair is not None
        assert {
            checkpoint.observed_at_ms for checkpoint in recovered_pair
        } == {recovered_at_ms}
        assert reader.checkpoint_pair_at(
            market.condition_id,
            recovered_at_ms,
            session_id=1,
        ) == recovered_pair
