from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from polybot.backtesting.contracts import BacktestError
from polybot.backtesting.state import ArchiveMarketState
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookCheckpoint,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    RecordedBookLevel,
)


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
