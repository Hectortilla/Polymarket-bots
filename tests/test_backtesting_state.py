from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal

import pytest

from polybot.backtesting.contracts import BacktestError
from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookChange,
    BookDeltaPayload,
    RecordedBookLevel,
)
from polybot.recording.contracts.records import (
    BookCheckpoint,
    CoverageGapRecord,
    RecordedEvent,
)
from polybot.recording.contracts.gaps import (
    CoverageGapPayload,
    CoverageGapReason,
)
from polybot.recording.contracts.market import (
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
)
from polybot.framework.events import Side


def test_metadata_identity_conflict_does_not_partially_mutate_indexes() -> None:
    state = ArchiveMarketState()
    original = _metadata()
    state.add_metadata(original)
    conflicting = replace(
        original,
        market_id="other-market-id",
        condition_id="other-condition",
        outcomes=(
            MarketOutcomeMetadata("Up", "other-up"),
            MarketOutcomeMetadata("Down", "other-down"),
        ),
    )

    with pytest.raises(BacktestError, match="slug maps to multiple"):
        state.add_metadata(conflicting)

    assert state.markets == (state.market_for_slug("market"),)
    assert state.markets[0].condition_id == "condition"


def test_checkpoint_pair_validation_is_atomic() -> None:
    state = ArchiveMarketState()
    state.add_metadata(_metadata())
    valid = _checkpoint("up", sequence=1)
    mismatched = replace(
        _checkpoint("down", sequence=2),
        identity=MarketIdentity(
            condition_id="unknown-condition",
            market_slug="market",
            token_id="down",
        ),
    )

    with pytest.raises(BacktestError, match="metadata"):
        state.seed_checkpoints((valid, mismatched))

    assert state.bootstrap_books({"market"}, received_at_ms=10) == ()


def test_blackout_hides_partial_recovery_and_emits_fresh_pair_atomically() -> None:
    state = ArchiveMarketState()
    state.add_metadata(_metadata())
    state.seed_checkpoints(
        (_checkpoint("up", sequence=1), _checkpoint("down", sequence=2))
    )
    initial = state.book_continuity("up")
    assert initial is not None
    assert (initial.revision, initial.blackout) == (0, False)

    invalidated = state.begin_blackout(_gap_record(ended_at_ms=20))

    assert invalidated == ("up", "down")
    assert state.is_blacked_out("market")
    assert asyncio.run(state.latest("up")) is None
    blackout = state.book_continuity("up")
    assert blackout is not None
    assert (blackout.revision, blackout.blackout) == (1, True)

    ignored = state.apply(
        _book_event("up", sequence=9, observed_at_ms=10, generation=1)
    )
    assert ignored.books == ()
    missing_baseline_delta = state.apply(
        _delta_event(sequence=11, observed_at_ms=18, generation=2)
    )
    assert missing_baseline_delta.books == ()
    first = state.apply(
        _book_event("up", sequence=12, observed_at_ms=19, generation=2)
    )
    assert first.books == ()
    assert asyncio.run(state.latest("up")) is None
    staged_delta = state.apply(
        _delta_event(sequence=13, observed_at_ms=19, generation=2)
    )
    assert staged_delta.books == ()
    assert asyncio.run(state.latest("up")) is None

    recovered = state.apply(
        _book_event("down", sequence=14, observed_at_ms=20, generation=2)
    )

    assert [book.token_id for book in recovered.books] == ["up", "down"]
    assert recovered.books[0].asks[0].price == Decimal("0.7")
    assert {book.received_at_ms for book in recovered.books} == {20}
    assert not state.is_blacked_out("market")
    assert asyncio.run(state.latest("up")) == recovered.books[0]
    continuity = state.book_continuity("up")
    assert continuity is not None
    assert (continuity.revision, continuity.blackout) == (1, False)


def test_token_scoped_open_gap_invalidates_whole_market_and_never_recovers() -> None:
    state = ArchiveMarketState()
    state.add_metadata(_metadata())
    state.add_metadata(
        replace(
            _metadata(),
            market_id="other-market-id",
            condition_id="other-condition",
            market_slug="other-market",
            outcomes=(
                MarketOutcomeMetadata("Up", "other-up"),
                MarketOutcomeMetadata("Down", "other-down"),
            ),
        )
    )
    state.seed_checkpoints(
        (_checkpoint("up", sequence=1), _checkpoint("down", sequence=2))
    )
    gap = _gap_record(ended_at_ms=None, affected_token_ids=("up",))

    assert state.begin_blackout(gap) == ("up", "down")
    assert state.apply(
        _book_event("up", sequence=11, observed_at_ms=20, generation=2)
    ).books == ()
    assert state.apply(
        _book_event("down", sequence=12, observed_at_ms=20, generation=2)
    ).books == ()
    assert state.is_blacked_out("market")
    assert not state.is_blacked_out("other-market")
    assert state.books == {}
    unaffected = state.book_continuity("other-up")
    assert unaffected is not None
    assert (unaffected.revision, unaffected.blackout) == (0, False)


def test_staged_pair_releases_atomically_at_closed_gap_end() -> None:
    state = ArchiveMarketState()
    state.add_metadata(_metadata())
    state.seed_checkpoints(
        (_checkpoint("up", sequence=1), _checkpoint("down", sequence=2))
    )
    state.begin_blackout(_gap_record(ended_at_ms=20))

    assert state.apply(
        _book_event("up", sequence=11, observed_at_ms=18, generation=2)
    ).books == ()
    assert state.apply(
        _book_event("down", sequence=12, observed_at_ms=19, generation=2)
    ).books == ()
    assert state.recover_books_at(19) == ()
    assert state.books == {}

    recovered = state.recover_books_at(20)

    assert [book.token_id for book in recovered] == ["up", "down"]
    assert {book.received_at_ms for book in recovered} == {20}
    assert not state.is_blacked_out("market")
    assert state.recover_books_at(20) == ()


def test_overlapping_closed_gaps_wait_for_the_last_recovery_boundary() -> None:
    state = ArchiveMarketState()
    state.add_metadata(_metadata())
    state.seed_checkpoints(
        (_checkpoint("up", sequence=1), _checkpoint("down", sequence=2))
    )
    state.begin_blackout(_gap_record(ended_at_ms=20))
    state.begin_blackout(
        _gap_record(
            ended_at_ms=25,
            gap_id=2,
            event_sequence=11,
            started_at_ms=12,
        )
    )

    assert state.apply(
        _book_event("up", sequence=12, observed_at_ms=18, generation=2)
    ).books == ()
    assert state.apply(
        _book_event("down", sequence=13, observed_at_ms=19, generation=2)
    ).books == ()
    assert state.recover_books_at(20) == ()

    recovered = state.recover_books_at(25)

    assert [book.token_id for book in recovered] == ["up", "down"]
    assert {book.received_at_ms for book in recovered} == {25}
    continuity = state.book_continuity("up")
    assert continuity is not None
    assert (continuity.revision, continuity.blackout) == (2, False)


def _metadata() -> MarketMetadataPayload:
    return MarketMetadataPayload(
        market_id="market-id",
        condition_id="condition",
        market_slug="market",
        question="Up or down?",
        events=(),
        outcomes=(
            MarketOutcomeMetadata("Up", "up"),
            MarketOutcomeMetadata("Down", "down"),
        ),
        active=True,
        closed=False,
        archived=False,
        start_at_ms=0,
        end_at_ms=100,
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


def _checkpoint(token_id: str, *, sequence: int) -> BookCheckpoint:
    return BookCheckpoint(
        sequence=sequence,
        session_id=1,
        subscription_generation=0,
        observed_at_ms=1,
        identity=MarketIdentity(
            condition_id="condition",
            market_slug="market",
            token_id=token_id,
        ),
        book=BookBaselinePayload(
            token_id=token_id,
            bids=(RecordedBookLevel(Decimal("0.4"), Decimal("1")),),
            asks=(RecordedBookLevel(Decimal("0.6"), Decimal("1")),),
        ),
    )


def _gap_record(
    *,
    ended_at_ms: int | None,
    affected_token_ids: tuple[str, ...] = ("up", "down"),
    gap_id: int = 1,
    event_sequence: int = 10,
    started_at_ms: int = 10,
) -> CoverageGapRecord:
    return CoverageGapRecord(
        gap_id=gap_id,
        event_sequence=event_sequence,
        session_id=1,
        subscription_generation=1,
        observed_at_ms=15,
        identity=MarketIdentity(
            condition_id="condition",
            market_slug="market",
        ),
        gap=CoverageGapPayload(
            reason=CoverageGapReason.DISCONNECT,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            affected_token_ids=affected_token_ids,
        ),
    )


def _book_event(
    token_id: str,
    *,
    sequence: int,
    observed_at_ms: int,
    generation: int,
) -> RecordedEvent:
    return RecordedEvent(
        sequence=sequence,
        session_id=1,
        subscription_generation=generation,
        observed_at_ms=observed_at_ms,
        source_timestamp_ms=None,
        identity=MarketIdentity(
            condition_id="condition",
            market_slug="market",
            token_id=token_id,
        ),
        payload=BookBaselinePayload(
            token_id=token_id,
            bids=(RecordedBookLevel(Decimal("0.4"), Decimal("1")),),
            asks=(RecordedBookLevel(Decimal("0.6"), Decimal("1")),),
        ),
    )


def _delta_event(
    *,
    sequence: int,
    observed_at_ms: int,
    generation: int,
) -> RecordedEvent:
    return RecordedEvent(
        sequence=sequence,
        session_id=1,
        subscription_generation=generation,
        observed_at_ms=observed_at_ms,
        source_timestamp_ms=None,
        identity=MarketIdentity(
            condition_id="condition",
            market_slug="market",
            token_id="up",
        ),
        payload=BookDeltaPayload(
            changes=(
                BookChange("up", Side.SELL, Decimal("0.6"), Decimal("0")),
                BookChange("up", Side.SELL, Decimal("0.7"), Decimal("1")),
            )
        ),
    )
