from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import polybot.recording.trimming as trimming_module
from polybot.backtesting.contracts import BacktestOptions
from polybot.backtesting.service import run_backtest
from polybot.backtesting.selection import (
    resolve_backtest_selection,
    validate_backtest_selection,
)
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.events import Side
from polybot.recording.archive import RecordingArchive, RecordingReader
from polybot.recording.archive_errors import (
    ArchiveFormatError,
    ArchiveIntegrityError,
    ArchiveLockedError,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookChange,
    BookCheckpoint,
    BookDeltaPayload,
    CoverageGapPayload,
    CoverageGapReason,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    PublicTradePayload,
    RecordedBookLevel,
    RecordedEvent,
    SessionIntegrityStatus,
    TickSizeChangePayload,
)
from polybot.recording.serialization import payload_json
from polybot.recording.trim_contracts import (
    DEFAULT_TRIM_BACKUP_SUFFIX,
    RecordingTrimError,
)
from polybot.recording.trim_planning import _clean_intervals
from polybot.recording.trimming import trim_recording


START_MS = 1_000
GAP_START_MS = 1_010
GAP_END_MS = 1_020
END_MS = 1_100
CONDITION_ID = "condition"
MARKET_SLUG = "market"
UP_TOKEN = "up-token"
DOWN_TOKEN = "down-token"
OTHER_CONDITION_ID = "other-condition"
OTHER_MARKET_SLUG = "other-market"
OTHER_UP_TOKEN = "other-up-token"
OTHER_DOWN_TOKEN = "other-down-token"


class _InspectingBot(BaseBot):
    def __init__(self) -> None:
        self.market_slugs_at_start: set[str] = set()
        self.book_tokens_at_start: set[str] = set()

    async def on_start(self, ctx: BotContext) -> None:
        for market_slug in (MARKET_SLUG, OTHER_MARKET_SLUG):
            market = await ctx.markets.find_by_slug(market_slug)
            if market is not None:
                self.market_slugs_at_start.add(market.slug)
        for token_id in (
            UP_TOKEN,
            DOWN_TOKEN,
            OTHER_UP_TOKEN,
            OTHER_DOWN_TOKEN,
        ):
            if await ctx.books.latest(token_id) is not None:
                self.book_tokens_at_start.add(token_id)


def _market() -> MarketMetadataPayload:
    return MarketMetadataPayload(
        market_id="market-id",
        condition_id=CONDITION_ID,
        market_slug=MARKET_SLUG,
        question="Up or down?",
        events=(),
        outcomes=(
            MarketOutcomeMetadata("Up", UP_TOKEN),
            MarketOutcomeMetadata("Down", DOWN_TOKEN),
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


def _identity(token_id: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        condition_id=CONDITION_ID,
        market_slug=MARKET_SLUG,
        token_id=token_id,
    )


def _other_market() -> MarketMetadataPayload:
    return replace(
        _market(),
        market_id="other-market-id",
        condition_id=OTHER_CONDITION_ID,
        market_slug=OTHER_MARKET_SLUG,
        outcomes=(
            MarketOutcomeMetadata("Up", OTHER_UP_TOKEN),
            MarketOutcomeMetadata("Down", OTHER_DOWN_TOKEN),
        ),
    )


def _identity_for(
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
    generation: int,
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


def _append_baselines(
    archive: RecordingArchive,
    *,
    observed_at_ms: int,
    generation: int,
) -> None:
    _append_market_baselines(
        archive,
        market=_market(),
        observed_at_ms=observed_at_ms,
        generation=generation,
    )


def _append_market_baselines(
    archive: RecordingArchive,
    *,
    market: MarketMetadataPayload,
    observed_at_ms: int,
    generation: int,
) -> None:
    token_ids = tuple(outcome.token_id for outcome in market.outcomes)
    archive.append_event(
        _event(
            archive,
            _book(token_ids[0]),
            observed_at_ms=observed_at_ms,
            identity=_identity_for(market, token_ids[0]),
            generation=generation,
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(token_ids[1]),
            observed_at_ms=observed_at_ms,
            identity=_identity_for(market, token_ids[1]),
            generation=generation,
        )
    )
    sequence = archive.next_sequence - 1
    archive.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=sequence,
                session_id=archive.session_id,
                subscription_generation=generation,
                observed_at_ms=observed_at_ms,
                identity=_identity_for(market, token_id),
                book=_book(token_id),
            )
            for token_id in token_ids
        )
    )


def _gapped_archive(path: Path) -> Path:
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    archive.close_gap(gap_id, ended_at_ms=GAP_END_MS)
    _append_baselines(archive, observed_at_ms=GAP_END_MS, generation=2)
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.close(ended_at_ms=END_MS)
    return path


def _staggered_recovery_archive(
    path: Path,
    *,
    checkpoint_at_ms: int,
    later_baselines_at_ms: int | None = None,
) -> Path:
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(UP_TOKEN),
            observed_at_ms=GAP_END_MS - 1,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(DOWN_TOKEN),
            observed_at_ms=GAP_END_MS,
            identity=_identity(DOWN_TOKEN),
            generation=2,
        )
    )
    archive.close_gap(gap_id, ended_at_ms=GAP_END_MS)
    checkpoint_sequence = archive.next_sequence - 1
    archive.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=checkpoint_sequence,
                session_id=archive.session_id,
                subscription_generation=2,
                observed_at_ms=checkpoint_at_ms,
                identity=_identity(token_id),
                book=_book(token_id),
            )
            for token_id in (UP_TOKEN, DOWN_TOKEN)
        )
    )
    tail_generation = 2
    if later_baselines_at_ms is not None:
        tail_generation = 3
        _append_baselines(
            archive,
            observed_at_ms=later_baselines_at_ms,
            generation=tail_generation,
        )
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=tail_generation,
        )
    )
    archive.close(ended_at_ms=END_MS)
    return path


def _archive_with_checkpoint_shifted_past_event(
    path: Path,
    *,
    payload: (
        BookDeltaPayload
        | MarketMetadataPayload
        | TickSizeChangePayload
    ),
) -> Path:
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    intervening_event = _event(
        archive,
        payload,
        observed_at_ms=GAP_START_MS,
        identity=(
            _identity()
            if isinstance(payload, MarketMetadataPayload)
            else _identity(UP_TOKEN)
        ),
        generation=1,
    )
    if isinstance(payload, MarketMetadataPayload):
        archive.append_metadata(intervening_event)
    else:
        archive.append_event(intervening_event)
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=1,
        )
    )
    archive.close(ended_at_ms=END_MS)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE book_checkpoints SET observed_at_ms = ? "
            "WHERE observed_at_ms = ?",
            (GAP_END_MS, START_MS + 1),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _open_gap_archive(path: Path, *, failed: bool = False) -> Path:
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    archive.close(
        clean=not failed,
        failure_reason="injected recorder failure" if failed else None,
        ended_at_ms=END_MS,
    )
    return path


def _middle_interval_archive(path: Path) -> Path:
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    first_gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    archive.close_gap(first_gap_id, ended_at_ms=GAP_END_MS)
    _append_baselines(archive, observed_at_ms=GAP_END_MS, generation=2)
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=1_070,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=1_080,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=1_080,
            identity=_identity(),
            generation=2,
        )
    )
    archive.close(ended_at_ms=END_MS)
    return path


def _gapped_two_market_archive(path: Path) -> Path:
    primary = _market()
    other = _other_market()
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG},{OTHER_MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    for market in (primary, other):
        archive.append_metadata(
            _event(
                archive,
                market,
                observed_at_ms=START_MS,
                identity=_identity_for(market),
                generation=1,
            )
        )
    archive.append_event(
        _event(
            archive,
            TickSizeChangePayload(
                token_id=OTHER_UP_TOKEN,
                old_tick_size=Decimal("0.01"),
                new_tick_size=Decimal("0.02"),
            ),
            observed_at_ms=START_MS,
            identity=_identity_for(other, OTHER_UP_TOKEN),
            generation=1,
        )
    )
    for market in (primary, other):
        _append_market_baselines(
            archive,
            market=market,
            observed_at_ms=START_MS + 1,
            generation=1,
        )
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    archive.close_gap(gap_id, ended_at_ms=GAP_END_MS)
    checkpoint_sequence = archive.next_sequence - 1
    archive.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=checkpoint_sequence,
                session_id=archive.session_id,
                subscription_generation=1,
                observed_at_ms=GAP_END_MS,
                identity=_identity_for(other, token_id),
                book=_book(token_id),
            )
            for token_id in (OTHER_UP_TOKEN, OTHER_DOWN_TOKEN)
        )
    )
    _append_market_baselines(
        archive,
        market=primary,
        observed_at_ms=GAP_END_MS,
        generation=2,
    )
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.close(ended_at_ms=END_MS)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(64 * 1024):
            digest.update(block)
    return digest.hexdigest()


def test_dry_run_selects_longest_tail_without_changing_archive(
    tmp_path: Path,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    before = _sha256(path)

    result = trim_recording(path, dry_run=True)

    assert result.replaced is False
    assert result.plan.start_at_ms == GAP_END_MS
    assert result.plan.end_at_ms == END_MS
    assert result.plan.duration_ms == END_MS - GAP_END_MS
    assert result.plan.source_gap_count == 1
    assert result.plan.source_event_count == 3
    assert _sha256(path) == before


def test_trim_replaces_archive_with_self_contained_gap_free_session(
    tmp_path: Path,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")

    result = trim_recording(path, keep_backup=False)

    assert result.replaced is True
    assert result.backup_path is None
    assert result.synthetic_event_count == 1
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        assert session.started_at_ms == GAP_END_MS
        assert session.ended_at_ms == END_MS
        assert reader.coverage_gaps() == ()
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection(reader, selection)
        assert selection.start_at_ms == GAP_END_MS
        assert selection.end_at_ms == END_MS
        assert selection.market_slugs == (MARKET_SLUG,)
        assert reader.event_count(session_id=session.session_id) == 4


def test_trimmed_archive_runs_a_default_backtest_without_selection_flags(
    tmp_path: Path,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    trim_recording(path, keep_backup=False)

    result = asyncio.run(
        run_backtest(
            BaseBot(),
            BotConfig(
                name="trim-backtest",
                market_slugs=(MARKET_SLUG,),
                event_max_age_ms=10_000,
            ),
            bot_spec="tests.test_recording_trim:BaseBot",
            options=BacktestOptions(
                archive_path=path,
                results_dir=tmp_path / "results",
            ),
        )
    )

    assert result.selection.start_at_ms == GAP_END_MS
    assert result.selection.end_at_ms == END_MS
    assert result.selection.market_slugs == (MARKET_SLUG,)
    assert result.event_count == 1


def test_trim_bootstraps_unaffected_market_book_and_dynamic_metadata(
    tmp_path: Path,
) -> None:
    path = _gapped_two_market_archive(tmp_path / "capture.sqlite3")

    result = trim_recording(path, keep_backup=False)

    assert result.synthetic_event_count == 4
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        markets = {
            market.market_slug: market
            for market in reader.markets_at(
                GAP_END_MS,
                session_id=session.session_id,
            )
        }
        assert tuple(sorted(markets)) == (MARKET_SLUG, OTHER_MARKET_SLUG)
        assert markets[OTHER_MARKET_SLUG].minimum_tick_size == Decimal("0.02")
        checkpoints = reader.checkpoint_pair_before(
            OTHER_CONDITION_ID,
            GAP_END_MS,
            session_id=session.session_id,
        )
        assert checkpoints is not None
        assert {checkpoint.book.token_id for checkpoint in checkpoints} == {
            OTHER_UP_TOKEN,
            OTHER_DOWN_TOKEN,
        }
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection(reader, selection)
        assert selection.market_slugs == (MARKET_SLUG, OTHER_MARKET_SLUG)
        assert reader.event_count(session_id=session.session_id) == 7

    bot = _InspectingBot()
    asyncio.run(
        run_backtest(
            bot,
            BotConfig(name="multi-market-trim", event_max_age_ms=10_000),
            bot_spec="tests.test_recording_trim:_InspectingBot",
            options=BacktestOptions(
                archive_path=path,
                results_dir=tmp_path / "multi-market-results",
            ),
        )
    )
    assert bot.market_slugs_at_start == {MARKET_SLUG, OTHER_MARKET_SLUG}
    assert bot.book_tokens_at_start == {
        UP_TOKEN,
        DOWN_TOKEN,
        OTHER_UP_TOKEN,
        OTHER_DOWN_TOKEN,
    }


def test_trim_bootstraps_unaffected_market_without_a_source_checkpoint(
    tmp_path: Path,
) -> None:
    path = _gapped_two_market_archive(tmp_path / "no-unaffected-checkpoint.sqlite3")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "DELETE FROM book_checkpoints WHERE market_slug = ?",
            (OTHER_MARKET_SLUG,),
        )
        connection.commit()
    finally:
        connection.close()

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        GAP_END_MS,
        END_MS,
    )
    with RecordingReader.for_replay(path) as reader:
        checkpoints = reader.checkpoint_pair_at(
            OTHER_CONDITION_ID,
            GAP_END_MS,
            session_id=reader.select_session().session_id,
        )
    assert checkpoints is not None
    assert {checkpoint.book.token_id for checkpoint in checkpoints} == {
        OTHER_UP_TOKEN,
        OTHER_DOWN_TOKEN,
    }


def test_trim_reconstructs_bootstrap_without_trusting_source_checkpoint(
    tmp_path: Path,
) -> None:
    path = _gapped_two_market_archive(tmp_path / "capture.sqlite3")
    connection = sqlite3.connect(path)
    try:
        for token_id in (OTHER_UP_TOKEN, OTHER_DOWN_TOKEN):
            connection.execute(
                "UPDATE book_checkpoints SET payload_json = ? "
                "WHERE token_id = ? AND observed_at_ms = ?",
                (
                    payload_json(
                        BookBaselinePayload(
                            token_id=token_id,
                            bids=(
                                RecordedBookLevel(
                                    Decimal("0.01"),
                                    Decimal("999"),
                                ),
                            ),
                            asks=(
                                RecordedBookLevel(
                                    Decimal("0.99"),
                                    Decimal("1"),
                                ),
                            ),
                        )
                    ),
                    token_id,
                    START_MS + 1,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    trim_recording(path, keep_backup=False)

    with RecordingReader.for_replay(path) as reader:
        books = {
            event.payload.token_id: event.payload
            for event in reader.iter_events(
                start_at_ms=GAP_END_MS,
                end_at_ms=GAP_END_MS,
                session_id=1,
                market_slug=OTHER_MARKET_SLUG,
            )
            if isinstance(event.payload, BookBaselinePayload)
        }
    assert set(books) == {OTHER_UP_TOKEN, OTHER_DOWN_TOKEN}
    assert all(
        book.bids == (
            RecordedBookLevel(Decimal("0.4"), Decimal("10")),
        )
        for book in books.values()
    )


def test_trim_uses_gap_end_checkpoint_after_staggered_recovery_baselines(
    tmp_path: Path,
) -> None:
    path = _staggered_recovery_archive(
        tmp_path / "staggered-recovery.sqlite3",
        checkpoint_at_ms=GAP_END_MS,
    )

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        GAP_END_MS,
        END_MS,
    )
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection(reader, selection)
    assert (selection.start_at_ms, selection.end_at_ms) == (
        GAP_END_MS,
        END_MS,
    )


def test_trim_ignores_boundary_baselines_recorded_before_the_gap_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stale-boundary-baselines.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    for token_id in (UP_TOKEN, DOWN_TOKEN):
        archive.append_event(
            _event(
                archive,
                _book(token_id),
                observed_at_ms=GAP_END_MS,
                identity=_identity(token_id),
                generation=2,
            )
        )
    gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_END_MS,
            identity=_identity(),
            generation=2,
        )
    )
    archive.close_gap(gap_id, ended_at_ms=GAP_END_MS)
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.close(ended_at_ms=END_MS)

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        START_MS,
        GAP_START_MS - 1,
    )


def test_trim_reconstructs_overlapping_token_scoped_recovery(
    tmp_path: Path,
) -> None:
    path = tmp_path / "token-scoped-recovery.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    up_gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=None,
                affected_token_ids=(UP_TOKEN,),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(UP_TOKEN),
            generation=1,
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(UP_TOKEN),
            observed_at_ms=GAP_START_MS + 5,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    down_gap_id = archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS + 6,
                ended_at_ms=None,
                affected_token_ids=(DOWN_TOKEN,),
            ),
            observed_at_ms=GAP_START_MS + 6,
            identity=_identity(DOWN_TOKEN),
            generation=1,
        )
    )
    archive.append_event(
        _event(
            archive,
            _book(DOWN_TOKEN),
            observed_at_ms=GAP_END_MS - 2,
            identity=_identity(DOWN_TOKEN),
            generation=2,
        )
    )
    archive.close_gap(up_gap_id, ended_at_ms=GAP_END_MS)
    archive.close_gap(down_gap_id, ended_at_ms=GAP_END_MS)
    checkpoint_sequence = archive.next_sequence - 1
    archive.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=checkpoint_sequence,
                session_id=archive.session_id,
                subscription_generation=2,
                observed_at_ms=GAP_END_MS,
                identity=_identity(token_id),
                book=_book(token_id),
            )
            for token_id in (UP_TOKEN, DOWN_TOKEN)
        )
    )
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.close(ended_at_ms=END_MS)

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        GAP_END_MS,
        END_MS,
    )
    with RecordingReader.for_replay(path) as reader:
        books = {
            event.payload.token_id: event.subscription_generation
            for event in reader.iter_events(
                start_at_ms=GAP_END_MS,
                end_at_ms=GAP_END_MS,
                session_id=reader.select_session().session_id,
            )
            if isinstance(event.payload, BookBaselinePayload)
        }
    assert books == {UP_TOKEN: 2, DOWN_TOKEN: 2}


def test_trim_uses_fresh_checkpoint_after_staggered_recovery_baselines(
    tmp_path: Path,
) -> None:
    checkpoint_at_ms = GAP_END_MS + 1
    path = _staggered_recovery_archive(
        tmp_path / "fresh-staggered-recovery.sqlite3",
        checkpoint_at_ms=checkpoint_at_ms,
    )

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        checkpoint_at_ms,
        END_MS,
    )
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection(reader, selection)
    assert (selection.start_at_ms, selection.end_at_ms) == (
        checkpoint_at_ms,
        END_MS,
    )


def test_trim_uses_recovery_checkpoint_when_a_later_baseline_pair_exists(
    tmp_path: Path,
) -> None:
    path = _staggered_recovery_archive(
        tmp_path / "recovery-with-later-baselines.sqlite3",
        checkpoint_at_ms=GAP_END_MS,
        later_baselines_at_ms=1_050,
    )

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        GAP_END_MS,
        END_MS,
    )
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection(reader, selection)
    assert (selection.start_at_ms, selection.end_at_ms) == (
        GAP_END_MS,
        END_MS,
    )


def test_trim_uses_fresh_recovery_checkpoint_when_later_baselines_exist(
    tmp_path: Path,
) -> None:
    checkpoint_at_ms = GAP_END_MS + 1
    path = _staggered_recovery_archive(
        tmp_path / "fresh-recovery-with-later-baselines.sqlite3",
        checkpoint_at_ms=checkpoint_at_ms,
        later_baselines_at_ms=1_050,
    )

    result = trim_recording(path, keep_backup=False)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        checkpoint_at_ms,
        END_MS,
    )
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        validate_backtest_selection(reader, selection)
    assert (selection.start_at_ms, selection.end_at_ms) == (
        checkpoint_at_ms,
        END_MS,
    )


def test_trim_keeps_default_hard_link_backup_of_original(tmp_path: Path) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    original_hash = _sha256(path)

    result = trim_recording(path)

    backup = path.with_name(f"{path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}")
    assert result.backup_path == backup
    assert backup.is_file()
    assert _sha256(backup) == original_hash
    assert _sha256(path) != original_hash
    with RecordingReader.for_replay(backup) as reader:
        assert len(reader.coverage_gaps()) == 1


def test_trim_preserves_source_file_permissions(tmp_path: Path) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    path.chmod(0o600)

    trim_recording(path, keep_backup=False)

    assert path.stat().st_mode & 0o777 == 0o600


def test_existing_backup_prevents_replacement(tmp_path: Path) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    before = _sha256(path)
    backup = path.with_name(f"{path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}")
    backup.write_text("already here", encoding="utf-8")

    with pytest.raises(RecordingTrimError, match="backup already exists"):
        trim_recording(path)

    assert _sha256(path) == before
    assert backup.read_text(encoding="utf-8") == "already here"


def test_failed_temporary_validation_leaves_original_and_no_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    before = _sha256(path)

    def fail_validation(*args: object, **kwargs: object) -> None:
        raise RecordingTrimError("injected validation failure")

    monkeypatch.setattr(
        trimming_module,
        "validate_trimmed_archive",
        fail_validation,
    )

    with pytest.raises(RecordingTrimError, match="injected validation failure"):
        trim_recording(path)

    assert _sha256(path) == before
    assert not path.with_name(
        f"{path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}"
    ).exists()
    assert not tuple(tmp_path.glob(f".{path.name}.trim-*"))


def test_failed_atomic_replace_leaves_original_and_removes_new_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    before = _sha256(path)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(trimming_module.os, "replace", fail_replace)

    with pytest.raises(
        RecordingTrimError,
        match=(
            "recording was not replaced; filesystem failure while "
            "installing the replacement: injected replace failure"
        ),
    ):
        trim_recording(path)

    assert _sha256(path) == before
    assert not path.with_name(
        f"{path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}"
    ).exists()
    assert not tuple(tmp_path.glob(f".{path.name}.trim-*"))


def test_post_replace_sync_failure_reports_that_replacement_happened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    before = _sha256(path)

    def fail_sync(directory: Path) -> None:
        raise OSError("injected directory sync failure")

    monkeypatch.setattr(trimming_module, "fsync_directory", fail_sync)

    with pytest.raises(
        RecordingTrimError,
        match=(
            "recording was replaced; filesystem failure while synchronizing "
            "the replacement: injected directory sync failure"
        ),
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) != before
    with RecordingReader.for_replay(path) as reader:
        assert reader.coverage_gaps() == ()


def test_post_replace_cleanup_failure_reports_that_replacement_happened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    before = _sha256(path)

    def fail_cleanup(temporary_path: Path) -> None:
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(
        trimming_module,
        "remove_archive_artifacts",
        fail_cleanup,
    )

    with pytest.raises(
        RecordingTrimError,
        match=(
            "recording was replaced; trim operation completed but cleanup "
            "failed; cleanup failure while removing temporary archive files: "
            "injected cleanup failure"
        ),
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) != before


def test_failed_backup_cleanup_reports_retained_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    backup = path.with_name(f"{path.name}{DEFAULT_TRIM_BACKUP_SUFFIX}")
    original_hash = _sha256(path)
    original_unlink = Path.unlink

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    def fail_backup_unlink(
        candidate: Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        if candidate == backup:
            raise OSError("injected backup cleanup failure")
        original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(trimming_module.os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_backup_unlink)

    with pytest.raises(
        RecordingTrimError,
        match=(
            r"recording was not replaced; filesystem failure while installing "
            r"the replacement: injected replace failure; backup retained at .*"
            r"; cleanup failure while removing the temporary backup: injected "
            r"backup cleanup failure"
        ),
    ):
        trim_recording(path)

    assert _sha256(path) == original_hash
    assert _sha256(backup) == original_hash


def test_path_resolution_failure_is_reported_as_pre_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolve(candidate: Path) -> Path:
        raise OSError("injected resolution failure")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(
        RecordingTrimError,
        match=(
            "recording was not replaced; filesystem failure while resolving "
            "the source archive path: injected resolution failure"
        ),
    ):
        trim_recording("capture.sqlite3", dry_run=True)


def test_home_expansion_failure_is_reported_as_pre_replace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_expanduser(candidate: Path) -> Path:
        raise RuntimeError("injected home expansion failure")

    monkeypatch.setattr(Path, "expanduser", fail_expanduser)

    with pytest.raises(
        RecordingTrimError,
        match=(
            "recording was not replaced; path normalization failed: "
            "injected home expansion failure"
        ),
    ):
        trim_recording("~/capture.sqlite3", dry_run=True)


def test_trim_rejects_checkpoint_with_historical_generation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "historical-checkpoint-generation.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    _append_baselines(archive, observed_at_ms=GAP_END_MS, generation=2)
    archive.append_event(
        _event(
            archive,
            BookDeltaPayload(
                changes=(
                    BookChange(
                        token_id=UP_TOKEN,
                        side=Side.SELL,
                        price=Decimal("0.6"),
                        size=Decimal("9"),
                    ),
                )
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=2,
        )
    )
    archive.close(ended_at_ms=END_MS)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE book_checkpoints SET subscription_generation = 1 "
            "WHERE observed_at_ms = ?",
            (GAP_END_MS,),
        )
        connection.commit()
    finally:
        connection.close()
    before = _sha256(path)

    with pytest.raises(
        (RecordingTrimError, ArchiveFormatError),
        match="checkpoint",
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) == before


def test_trim_rejects_checkpoint_that_skips_a_canonical_book_event(
    tmp_path: Path,
) -> None:
    path = _archive_with_checkpoint_shifted_past_event(
        tmp_path / "checkpoint-skips-book-event.sqlite3",
        payload=BookDeltaPayload(
            changes=(
                BookChange(
                    token_id=UP_TOKEN,
                    side=Side.SELL,
                    price=Decimal("0.6"),
                    size=Decimal("7"),
                ),
            )
        ),
    )
    before = _sha256(path)

    with pytest.raises(
        (RecordingTrimError, ArchiveFormatError, ArchiveIntegrityError),
        match="checkpoint",
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) == before


def test_trim_rejects_events_whose_observation_time_moves_backwards(
    tmp_path: Path,
) -> None:
    path = tmp_path / "backwards-event-time.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    for token_id in (UP_TOKEN, DOWN_TOKEN):
        archive.append_event(
            _event(
                archive,
                _book(token_id),
                observed_at_ms=START_MS + 1,
                identity=_identity(token_id),
                generation=1,
            )
        )
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.55"),
                size=Decimal("2"),
                side=Side.BUY,
            ),
            observed_at_ms=END_MS - 10,
            identity=_identity(UP_TOKEN),
            generation=1,
        )
    )
    archive.close(ended_at_ms=END_MS)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE events SET observed_at_ms = ? WHERE sequence = 3",
            (END_MS - 40,),
        )
        connection.execute(
            "UPDATE events SET observed_at_ms = ? WHERE sequence = 4",
            (END_MS - 50,),
        )
        connection.commit()
    finally:
        connection.close()
    before = _sha256(path)

    with pytest.raises(RecordingTrimError, match="timeline"):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) == before


def test_trim_rejects_checkpoint_that_skips_a_tick_size_change(
    tmp_path: Path,
) -> None:
    path = _archive_with_checkpoint_shifted_past_event(
        tmp_path / "checkpoint-skips-tick-change.sqlite3",
        payload=TickSizeChangePayload(
            token_id=UP_TOKEN,
            old_tick_size=Decimal("0.01"),
            new_tick_size=Decimal("0.02"),
        ),
    )
    before = _sha256(path)

    with pytest.raises(
        (RecordingTrimError, ArchiveFormatError, ArchiveIntegrityError),
        match="checkpoint",
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) == before


def test_trim_rejects_checkpoint_that_skips_a_metadata_revision(
    tmp_path: Path,
) -> None:
    path = _archive_with_checkpoint_shifted_past_event(
        tmp_path / "checkpoint-skips-metadata.sqlite3",
        payload=replace(_market(), question="Updated question?"),
    )
    before = _sha256(path)

    with pytest.raises(
        (RecordingTrimError, ArchiveFormatError, ArchiveIntegrityError),
        match="checkpoint",
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) == before


@pytest.mark.parametrize("corruption", ("event_tokens", "checkpoint", "anomaly"))
def test_auxiliary_row_corruption_prevents_replacement(
    tmp_path: Path,
    corruption: str,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    connection = sqlite3.connect(path)
    try:
        if corruption == "event_tokens":
            connection.execute(
                "DELETE FROM event_tokens WHERE sequence = ("
                "SELECT sequence FROM events WHERE payload_kind = 'public_trade'"
                ")"
            )
        elif corruption == "checkpoint":
            for token_id in (UP_TOKEN, DOWN_TOKEN):
                connection.execute(
                    "UPDATE book_checkpoints SET payload_json = ? "
                    "WHERE token_id = ? AND observed_at_ms >= ?",
                    (
                        payload_json(
                            BookBaselinePayload(
                                token_id=token_id,
                                bids=(
                                    RecordedBookLevel(
                                        Decimal("0.01"),
                                        Decimal("999"),
                                    ),
                                ),
                                asks=(
                                    RecordedBookLevel(
                                        Decimal("0.99"),
                                        Decimal("1"),
                                    ),
                                ),
                            )
                        ),
                        token_id,
                        GAP_END_MS,
                    ),
                )
        else:
            connection.execute(
                """
                INSERT INTO capture_anomalies (
                    session_id, subscription_generation, observed_at_ms,
                    condition_id, market_slug, token_id, failure_kind,
                    payload_json
                ) VALUES (1, 2, ?, ?, ?, ?, 'split_revision_timeout', '{}')
                """,
                (GAP_END_MS, CONDITION_ID, MARKET_SLUG, UP_TOKEN),
            )
        connection.commit()
    finally:
        connection.close()
    before = _sha256(path)

    with pytest.raises(
        (RecordingTrimError, ArchiveFormatError),
        match="(inconsistent|malformed)",
    ):
        trim_recording(path, keep_backup=False)

    assert _sha256(path) == before


def test_trim_preserves_unavailable_capture_anomaly_provenance(
    tmp_path: Path,
) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    connection = sqlite3.connect(path)
    try:
        connection.execute("DELETE FROM recording_features")
        connection.commit()
    finally:
        connection.close()

    trim_recording(path, keep_backup=False)

    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        assert reader.has_capture_anomaly_journal is False
        assert reader.capture_anomaly_journal_available(session.session_id) is False


def test_active_writer_prevents_trim(tmp_path: Path) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    writer = RecordingArchive.resume(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=END_MS + 10,
    )
    try:
        with pytest.raises(ArchiveLockedError, match="already open for writing"):
            trim_recording(path, session_id=1, dry_run=True)
    finally:
        writer.close(ended_at_ms=END_MS + 20)


def test_multiple_sessions_require_explicit_selection(tmp_path: Path) -> None:
    path = _gapped_archive(tmp_path / "capture.sqlite3")
    resumed = RecordingArchive.resume(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=END_MS + 10,
    )
    _append_baselines(resumed, observed_at_ms=END_MS + 10, generation=3)
    resumed.close(ended_at_ms=END_MS + 20)

    with pytest.raises(
        ArchiveFormatError,
        match=r"explicit --session ID; available session IDs: 1, 2",
    ):
        trim_recording(path, dry_run=True)

    result = trim_recording(path, session_id=1, dry_run=True)
    assert result.plan.source_session.session_id == 1

    clean_result = trim_recording(path, session_id=2, dry_run=True)
    assert clean_result.plan.source_session.session_id == 2
    assert clean_result.plan.source_gap_count == 0
    assert (
        clean_result.plan.start_at_ms,
        clean_result.plan.end_at_ms,
    ) == (END_MS + 10, END_MS + 20)


def test_clean_session_starts_trim_at_its_first_recorded_event(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delayed-first-event.sqlite3"
    first_event_ms = START_MS + 5
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=first_event_ms,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(
        archive,
        observed_at_ms=first_event_ms + 1,
        generation=1,
    )
    archive.close(ended_at_ms=END_MS)

    result = trim_recording(path, keep_backup=False)

    assert result.plan.start_at_ms == first_event_ms
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
    assert selection.start_at_ms == first_event_ms
    assert selection.end_at_ms == END_MS


def test_open_gap_selects_clean_prefix(tmp_path: Path) -> None:
    path = _open_gap_archive(tmp_path / "capture.sqlite3")

    result = trim_recording(path, dry_run=True)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        START_MS,
        GAP_START_MS - 1,
    )


def test_failed_source_becomes_complete_trim_with_exact_default_range(
    tmp_path: Path,
) -> None:
    path = _open_gap_archive(tmp_path / "capture.sqlite3", failed=True)

    result = trim_recording(path, keep_backup=False)

    assert result.plan.source_session.integrity_status is SessionIntegrityStatus.FAILED
    with RecordingReader.for_replay(path) as reader:
        session = reader.select_session()
        assert session.clean_close is True
        assert session.integrity_status is SessionIntegrityStatus.COMPLETE
        selection = resolve_backtest_selection(
            reader,
            session,
            BacktestOptions(archive_path=path),
        )
        assert (selection.start_at_ms, selection.end_at_ms) == (
            START_MS,
            GAP_START_MS - 1,
        )


def test_two_gaps_select_longest_clean_middle_interval(tmp_path: Path) -> None:
    path = _middle_interval_archive(tmp_path / "capture.sqlite3")

    result = trim_recording(path, dry_run=True)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (
        GAP_END_MS,
        1_079,
    )


def test_clean_interval_boundaries_follow_half_open_gap_semantics() -> None:
    records = (
        SimpleNamespace(
            gap=CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=10,
                ended_at_ms=20,
            )
        ),
        SimpleNamespace(
            gap=CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=15,
                ended_at_ms=25,
            )
        ),
        SimpleNamespace(
            gap=CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=30,
                ended_at_ms=None,
            )
        ),
    )

    intervals = _clean_intervals(0, 40, records)

    assert tuple(
        (interval.start_at_ms, interval.end_at_ms) for interval in intervals
    ) == ((0, 9), (25, 29))


def test_zero_duration_gap_does_not_split_a_clean_interval() -> None:
    records = (
        SimpleNamespace(
            gap=CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=20,
                ended_at_ms=20,
            )
        ),
    )

    intervals = _clean_intervals(0, 40, records)

    assert tuple(
        (interval.start_at_ms, interval.end_at_ms) for interval in intervals
    ) == ((0, 40),)


def test_zero_duration_gap_does_not_reduce_the_trim_plan(tmp_path: Path) -> None:
    path = tmp_path / "zero-duration-gap.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    archive.append_metadata(
        _event(
            archive,
            _market(),
            observed_at_ms=START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=START_MS + 1, generation=1)
    archive.append_gap(
        _event(
            archive,
            CoverageGapPayload(
                reason=CoverageGapReason.DISCONNECT,
                started_at_ms=GAP_START_MS,
                ended_at_ms=GAP_START_MS,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=GAP_START_MS,
            identity=_identity(),
            generation=1,
        )
    )
    _append_baselines(archive, observed_at_ms=GAP_START_MS, generation=2)
    archive.close(ended_at_ms=END_MS)

    result = trim_recording(path, dry_run=True)

    assert (result.plan.start_at_ms, result.plan.end_at_ms) == (START_MS, END_MS)
