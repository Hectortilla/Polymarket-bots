from __future__ import annotations

import asyncio
import csv
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from polybot.backtesting.contracts import (
    BacktestError,
    BacktestFailureReason,
    BacktestOptions,
)
from polybot.backtesting.service import run_backtest
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.performance.artifacts import PerformanceOutputExistsError
from polybot.recording.archive import (
    INTERRUPTED_SESSION_REASON,
    RecordingArchive,
    RecordingReader,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookChange,
    BookCheckpoint,
    BookDeltaPayload,
    CoverageGapPayload,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    PublicTradePayload,
    RecordedBookLevel,
    RecordedEvent,
    ResolutionPayload,
    SessionIntegrityStatus,
)


START_MS = 1_700_000_000_000
MARKET_SLUG = "btc-updown-5m-1700000000"
CONDITION_ID = "condition-btc"
UP_TOKEN = "token-up"
DOWN_TOKEN = "token-down"
NEXT_MARKET_SLUG = "btc-updown-5m-1700000001"
NEXT_CONDITION_ID = "condition-btc-next"
NEXT_UP_TOKEN = "token-next-up"
NEXT_DOWN_TOKEN = "token-next-down"
ROLLOVER_MS = START_MS + 1_000


@dataclass(frozen=True, slots=True)
class _ArchiveWindow:
    path: Path
    start_ms: int
    end_ms: int


class _TrackingBot(BaseBot):
    def __init__(self) -> None:
        self.start_count = 0
        self.stop_count = 0
        self.books: list[BookSnapshot] = []
        self.resolutions: list[MarketResolutionEvent] = []

    async def on_start(self, ctx: BotContext) -> None:
        self.start_count += 1

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        self.books.append(book)

    async def on_market_resolved(
        self,
        ctx: BotContext,
        event: MarketResolutionEvent,
    ) -> None:
        self.resolutions.append(event)

    async def on_stop(self, ctx: BotContext) -> None:
        self.stop_count += 1


class _BuyOnceBot(_TrackingBot):
    def __init__(self, *, size: Decimal = Decimal("2")) -> None:
        super().__init__()
        self.size = size
        self.fill: FillEvent | None = None

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        await super().on_book(ctx, book)
        if book.token_id != UP_TOKEN or self.fill is not None:
            return
        self.fill = await ctx.broker.submit(
            OrderRequest(
                token_id=UP_TOKEN,
                side=Side.BUY,
                price=Decimal("0.70"),
                size=self.size,
                market_slug=MARKET_SLUG,
                condition_id=CONDITION_ID,
                source_id="entry-1",
                reason="synthetic-entry",
            )
        )


class _SeededBuyBot(_BuyOnceBot):
    async def on_start(self, ctx: BotContext) -> None:
        await super().on_start(ctx)
        self.size = ctx.rng.choice((Decimal("1"), Decimal("2"), Decimal("3")))


class _SleepingBot(_TrackingBot):
    def __init__(self) -> None:
        super().__init__()
        self._slept = False
        self._callback_depth = 0
        self.max_callback_depth = 0

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        self._callback_depth += 1
        self.max_callback_depth = max(self.max_callback_depth, self._callback_depth)
        try:
            self.books.append(book)
            if book.token_id == UP_TOKEN and not self._slept:
                self._slept = True
                await ctx.clock.sleep(0.010)
        finally:
            self._callback_depth -= 1


class _FailingBot(_TrackingBot):
    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        raise RuntimeError("strategy exploded")


class _RolloverBot(_TrackingBot):
    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        slug = MARKET_SLUG if now_ms < ROLLOVER_MS else NEXT_MARKET_SLUG
        return (StreamRule(StreamRelation.INDEPENDENT, (slug,), ()),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        if now_ms >= ROLLOVER_MS:
            return ()
        return (
            StreamRule(
                StreamRelation.INDEPENDENT,
                (NEXT_MARKET_SLUG,),
                (),
            ),
        )


def _metadata(*, fee_rate: Decimal = Decimal("0")) -> MarketMetadataPayload:
    return MarketMetadataPayload(
        market_id="market-btc",
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
        start_at_ms=START_MS,
        end_at_ms=START_MS + 60_000,
        closed_at_ms=None,
        order_book_enabled=True,
        accepting_orders=True,
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        seconds_delay=0,
        neg_risk=False,
        fees_enabled=fee_rate > 0,
        fee_type=None,
        fee_schedule=None,
        fee_rate=fee_rate,
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


def _next_metadata() -> MarketMetadataPayload:
    original = _metadata()
    return MarketMetadataPayload(
        market_id="market-btc-next",
        condition_id=NEXT_CONDITION_ID,
        market_slug=NEXT_MARKET_SLUG,
        question=original.question,
        events=original.events,
        outcomes=(
            MarketOutcomeMetadata("Up", NEXT_UP_TOKEN),
            MarketOutcomeMetadata("Down", NEXT_DOWN_TOKEN),
        ),
        active=original.active,
        closed=original.closed,
        archived=original.archived,
        start_at_ms=ROLLOVER_MS,
        end_at_ms=ROLLOVER_MS + 60_000,
        closed_at_ms=original.closed_at_ms,
        order_book_enabled=original.order_book_enabled,
        accepting_orders=original.accepting_orders,
        minimum_tick_size=original.minimum_tick_size,
        minimum_order_size=original.minimum_order_size,
        seconds_delay=original.seconds_delay,
        neg_risk=original.neg_risk,
        fees_enabled=original.fees_enabled,
        fee_type=original.fee_type,
        fee_schedule=original.fee_schedule,
        fee_rate=original.fee_rate,
        question_id=original.question_id,
        neg_risk_request_id=original.neg_risk_request_id,
        resolution_status=original.resolution_status,
        resolution_source=original.resolution_source,
        resolved_by=original.resolved_by,
        resolved=False,
        winning_token_id=None,
        winning_outcome=None,
    )


def _next_identity(token_id: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        condition_id=NEXT_CONDITION_ID,
        market_slug=NEXT_MARKET_SLUG,
        token_id=token_id,
    )


def _baseline(
    token_id: str,
    *,
    ask_size: Decimal = Decimal("10"),
) -> BookBaselinePayload:
    return BookBaselinePayload(
        token_id=token_id,
        bids=(RecordedBookLevel(Decimal("0.40"), Decimal("10")),),
        asks=(RecordedBookLevel(Decimal("0.60"), ask_size),),
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
        subscription_generation=1,
        observed_at_ms=observed_at_ms,
        source_timestamp_ms=observed_at_ms - 1,
        identity=identity,
        payload=payload,  # type: ignore[arg-type]
    )


def _append_prefix(
    archive: RecordingArchive,
    *,
    fee_rate: Decimal = Decimal("0"),
    up_ask_size: Decimal = Decimal("10"),
    include_down: bool = True,
) -> None:
    archive.append_metadata(
        _event(
            archive,
            _metadata(fee_rate=fee_rate),
            observed_at_ms=START_MS,
            identity=_identity(),
        )
    )
    archive.append_event(
        _event(
            archive,
            _baseline(UP_TOKEN, ask_size=up_ask_size),
            observed_at_ms=START_MS + 1,
            identity=_identity(UP_TOKEN),
        )
    )
    if include_down:
        archive.append_event(
            _event(
                archive,
                _baseline(DOWN_TOKEN),
                observed_at_ms=START_MS + 2,
                identity=_identity(DOWN_TOKEN),
            )
        )


def _append_trade(archive: RecordingArchive, observed_at_ms: int) -> None:
    archive.append_event(
        _event(
            archive,
            PublicTradePayload(
                token_id=UP_TOKEN,
                price=Decimal("0.50"),
                size=Decimal("1"),
                side=Side.BUY,
            ),
            observed_at_ms=observed_at_ms,
            identity=_identity(UP_TOKEN),
        )
    )


def _append_ask_change(
    archive: RecordingArchive,
    *,
    observed_at_ms: int,
    token_id: str,
    old_price: Decimal,
    new_price: Decimal,
) -> None:
    archive.append_event(
        _event(
            archive,
            BookDeltaPayload(
                changes=(
                    BookChange(token_id, Side.SELL, old_price, Decimal("0")),
                    BookChange(token_id, Side.SELL, new_price, Decimal("10")),
                )
            ),
            observed_at_ms=observed_at_ms,
            identity=_identity(token_id),
        )
    )


def _basic_archive(
    tmp_path: Path,
    *,
    name: str = "capture.sqlite3",
    tail_offset_ms: int = 20,
    fee_rate: Decimal = Decimal("0"),
    up_ask_size: Decimal = Decimal("10"),
) -> _ArchiveWindow:
    path = tmp_path / name
    archive = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(
        archive,
        fee_rate=fee_rate,
        up_ask_size=up_ask_size,
    )
    end_ms = START_MS + tail_offset_ms
    _append_trade(archive, end_ms)
    archive.close()
    return _ArchiveWindow(path, START_MS, end_ms)


def _config(**overrides: object) -> BotConfig:
    values: dict[str, object] = {
        "name": "backtest-test",
        "market_slugs": (MARKET_SLUG,),
        "paper_latency_ms": 0,
        "paper_latency_jitter_ms": 0,
        "event_max_age_ms": 60_000,
        "paper_portfolio_usdc": Decimal("100"),
        "max_order_size": Decimal("10"),
        "max_slippage_pct": Decimal("0.20"),
    }
    values.update(overrides)
    return BotConfig(**values)  # type: ignore[arg-type]


def _run(
    bot: BaseBot,
    archive: _ArchiveWindow,
    results_dir: Path,
    *,
    config: BotConfig | None = None,
    seed: int = 0,
    start_ms: int | None = None,
):
    return asyncio.run(
        run_backtest(
            bot,
            config or _config(),
            bot_spec="tests.test_backtesting:create",
            options=BacktestOptions(
                archive_path=archive.path,
                start_at_ms=start_ms,
                end_at_ms=archive.end_ms,
                seed=seed,
                results_dir=results_dir,
                report_interval_ms=5,
            ),
        )
    )


def _summary(results_dir: Path) -> dict[str, object]:
    return json.loads((results_dir / "summary.json").read_text(encoding="utf-8"))


def _orders(results_dir: Path) -> list[dict[str, str]]:
    with (results_dir / "orders.csv").open(
        encoding="utf-8",
        newline="",
    ) as source:
        return list(csv.DictReader(source))


def test_backtest_no_trade_runs_hooks_once_and_writes_complete_artifacts(
    tmp_path: Path,
) -> None:
    archive = _basic_archive(tmp_path)
    bot = _TrackingBot()

    result = _run(bot, archive, tmp_path / "results")
    summary = _summary(result.results_dir)

    assert (bot.start_count, bot.stop_count) == (1, 1)
    assert [(book.token_id, book.received_at_ms) for book in bot.books] == [
        (UP_TOKEN, START_MS + 2),
        (DOWN_TOKEN, START_MS + 2),
    ]
    assert result.selection.start_at_ms == START_MS + 2
    assert result.event_count == 1
    assert result.accepted_dispatch_count == 2
    assert summary["status"] == "completed"
    assert summary["selection"]["replay_cutoff_sequence"] == 4
    assert summary["timing"] == {
        "started_at_ms": START_MS + 2,
        "ended_at_ms": archive.end_ms,
        "virtual_duration_ms": archive.end_ms - (START_MS + 2),
    }
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["initial_cash_usdc"] == "100"
    assert metrics["final_cash_usdc"] == "100"
    assert metrics["final_equity_usdc"] == "100"
    assert metrics["net_pnl_usdc"] == "0"
    assert metrics["return"] == "0"
    assert metrics["order_count"] == 0
    assert (result.results_dir / "equity.csv").is_file()
    assert _orders(result.results_dir) == []


def test_backtest_partial_fill_fees_and_open_position_metrics(tmp_path: Path) -> None:
    archive = _basic_archive(
        tmp_path,
        fee_rate=Decimal("0.05"),
        up_ask_size=Decimal("1"),
    )
    bot = _BuyOnceBot()

    result = _run(bot, archive, tmp_path / "results")
    summary = _summary(result.results_dir)

    assert bot.fill is not None
    assert bot.fill.status is OrderStatus.PARTIAL
    assert bot.fill.filled_size == Decimal("1")
    assert bot.fill.average_price == Decimal("0.60")
    assert bot.fill.fee_usdc == Decimal("0.01200")
    assert _orders(result.results_dir)[0] == {
        "submitted_at_ms": str(START_MS + 2),
        "completed_at_ms": str(START_MS + 2),
        "order_id": "paper-1",
        "market_slug": MARKET_SLUG,
        "condition_id": CONDITION_ID,
        "token_id": UP_TOKEN,
        "side": "BUY",
        "requested_price": "0.70",
        "requested_size": "2",
        "status": "partial",
        "filled_size": "1",
        "average_price": "0.60",
        "fee_usdc": "0.01200",
        "reject_reason": "",
        "reject_message": "",
        "strategy_reason": "synthetic-entry",
        "source_id": "entry-1",
    }
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["final_cash_usdc"] == "99.38800"
    assert metrics["final_equity_usdc"] == "99.78800"
    assert metrics["gross_pnl_usdc"] == "-0.20000"
    assert metrics["net_pnl_usdc"] == "-0.21200"
    assert metrics["fees_usdc"] == "0.01200"
    assert metrics["filled_notional_usdc"] == "0.60"
    assert summary["open_positions"] == [
        {
            "token_id": UP_TOKEN,
            "size": "1",
            "average_entry_price": "0.60",
            "executable_mark": "0.40",
            "last_executable_mark": None,
            "market_value_usdc": "0.40",
            "valuation_status": "fresh",
        }
    ]


def test_backtest_settles_recorded_resolution_at_contractual_payout(
    tmp_path: Path,
) -> None:
    path = tmp_path / "resolved.sqlite3"
    archive_writer = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(archive_writer)
    end_ms = START_MS + 10
    archive_writer.append_event(
        _event(
            archive_writer,
            ResolutionPayload(
                token_ids=(UP_TOKEN, DOWN_TOKEN),
                winning_token_id=UP_TOKEN,
                winning_outcome="Up",
                source="synthetic",
                resolution_id="resolution-1",
            ),
            observed_at_ms=end_ms,
            identity=_identity(),
        )
    )
    archive_writer.close()
    archive = _ArchiveWindow(path, START_MS, end_ms)
    bot = _BuyOnceBot()

    result = _run(bot, archive, tmp_path / "results")
    summary = _summary(result.results_dir)

    assert bot.fill is not None and bot.fill.status is OrderStatus.FILLED
    assert len(bot.resolutions) == 1
    assert bot.resolutions[0].winning_token_id == UP_TOKEN
    assert bot.resolutions[0].resolved_at_ms == end_ms
    assert result.resolution_count == 1
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["final_cash_usdc"] == "100.80000"
    assert metrics["final_equity_usdc"] == "100.80000"
    assert metrics["net_pnl_usdc"] == "0.80000"
    assert metrics["resolution_count"] == 1
    assert summary["open_positions"] == []


def test_broker_latency_uses_intervening_delta_for_fill_time_book(
    tmp_path: Path,
) -> None:
    path = tmp_path / "latency.sqlite3"
    archive_writer = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(archive_writer)
    _append_ask_change(
        archive_writer,
        observed_at_ms=START_MS + 7,
        token_id=UP_TOKEN,
        old_price=Decimal("0.60"),
        new_price=Decimal("0.70"),
    )
    end_ms = START_MS + 20
    _append_trade(archive_writer, end_ms)
    archive_writer.close()
    archive = _ArchiveWindow(path, START_MS, end_ms)
    bot = _BuyOnceBot()

    result = _run(
        bot,
        archive,
        tmp_path / "results",
        config=_config(paper_latency_ms=10),
    )

    assert bot.fill is not None
    assert bot.fill.status is OrderStatus.FILLED
    assert bot.fill.received_at_ms == START_MS + 12
    assert bot.fill.average_price == Decimal("0.70")
    assert _orders(result.results_dir)[0]["average_price"] == "0.70"


def test_callback_latency_is_non_reentrant_and_coalesces_in_marker_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "coalescing.sqlite3"
    archive_writer = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(archive_writer)
    for old_price, new_price in (
        (Decimal("0.60"), Decimal("0.65")),
        (Decimal("0.65"), Decimal("0.70")),
    ):
        _append_ask_change(
            archive_writer,
            observed_at_ms=START_MS + 5,
            token_id=UP_TOKEN,
            old_price=old_price,
            new_price=new_price,
        )
    _append_ask_change(
        archive_writer,
        observed_at_ms=START_MS + 5,
        token_id=DOWN_TOKEN,
        old_price=Decimal("0.60"),
        new_price=Decimal("0.65"),
    )
    end_ms = START_MS + 20
    _append_trade(archive_writer, end_ms)
    archive_writer.close()
    archive = _ArchiveWindow(path, START_MS, end_ms)
    bot = _SleepingBot()

    result = _run(bot, archive, tmp_path / "results")

    assert bot.max_callback_depth == 1
    assert [
        (book.token_id, min(level.price for level in book.asks))
        for book in bot.books
    ] == [
        (UP_TOKEN, Decimal("0.60")),
        (DOWN_TOKEN, Decimal("0.65")),
        (UP_TOKEN, Decimal("0.70")),
    ]
    assert result.event_count == 4
    assert result.accepted_dispatch_count == 3


def test_same_archive_configuration_and_seed_produce_identical_artifacts(
    tmp_path: Path,
) -> None:
    archive = _basic_archive(tmp_path)
    first_bot = _SeededBuyBot()
    second_bot = _SeededBuyBot()

    first = _run(first_bot, archive, tmp_path / "first", seed=73)
    second = _run(second_bot, archive, tmp_path / "second", seed=73)

    assert first_bot.size == second_bot.size
    for artifact_name in ("summary.json", "equity.csv", "orders.csv"):
        assert (first.results_dir / artifact_name).read_bytes() == (
            second.results_dir / artifact_name
        ).read_bytes()

    different_bot = _SeededBuyBot()
    different = _run(
        different_bot,
        archive,
        tmp_path / "different",
        seed=3,
    )
    assert different_bot.size != first_bot.size
    assert _orders(different.results_dir)[0]["requested_size"] != (
        _orders(first.results_dir)[0]["requested_size"]
    )


def test_dynamic_rollover_suppresses_next_market_then_bootstraps_and_retains_prior(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rollover.sqlite3"
    archive_writer = RecordingArchive.create(
        path,
        target_identity="bot:tests.test_backtesting:create",
        started_at_ms=START_MS,
    )
    _append_prefix(archive_writer)
    archive_writer.append_metadata(
        _event(
            archive_writer,
            _next_metadata(),
            observed_at_ms=START_MS + 3,
            identity=_next_identity(),
        )
    )
    for offset, token_id in enumerate(
        (NEXT_UP_TOKEN, NEXT_DOWN_TOKEN),
        start=4,
    ):
        archive_writer.append_event(
            _event(
                archive_writer,
                _baseline(token_id),
                observed_at_ms=START_MS + offset,
                identity=_next_identity(token_id),
            )
        )
    _append_ask_change(
        archive_writer,
        observed_at_ms=ROLLOVER_MS + 1,
        token_id=UP_TOKEN,
        old_price=Decimal("0.60"),
        new_price=Decimal("0.65"),
    )
    end_ms = ROLLOVER_MS + 2
    _append_trade(archive_writer, end_ms)
    archive_writer.close()
    archive = _ArchiveWindow(path, START_MS, end_ms)
    bot = _RolloverBot()

    result = _run(
        bot,
        archive,
        tmp_path / "results",
        config=_config(market_slugs=()),
    )

    assert [book.market_slug for book in bot.books] == [
        MARKET_SLUG,
        MARKET_SLUG,
        NEXT_MARKET_SLUG,
        NEXT_MARKET_SLUG,
        MARKET_SLUG,
    ]
    assert [book.received_at_ms for book in bot.books[2:4]] == [
        ROLLOVER_MS,
        ROLLOVER_MS,
    ]
    assert result.accepted_dispatch_count == 5


def test_latency_past_selected_end_is_an_explicit_fill_rejection(
    tmp_path: Path,
) -> None:
    archive = _basic_archive(tmp_path, tail_offset_ms=5)
    bot = _BuyOnceBot()

    result = _run(
        bot,
        archive,
        tmp_path / "results",
        config=_config(paper_latency_ms=10),
    )

    assert bot.fill is not None
    assert bot.fill.status is OrderStatus.REJECTED
    assert bot.fill.reject_reason is FillRejectReason.BACKTEST_DATA_EXHAUSTED
    assert bot.fill.received_at_ms == START_MS + 2
    order = _orders(result.results_dir)[0]
    assert order["reject_reason"] == "backtest_data_exhausted"
    assert _summary(result.results_dir)["status"] == "completed"


def test_active_session_is_locked_failed_prefix_replays_and_ambiguity_fails(
    tmp_path: Path,
) -> None:
    active_path = tmp_path / "active.sqlite3"
    active = RecordingArchive.create(
        active_path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(active)
    _append_trade(active, START_MS + 10)
    bot = _TrackingBot()
    try:
        with pytest.raises(BacktestError) as active_error:
            _run(
                bot,
                _ArchiveWindow(active_path, START_MS, START_MS + 10),
                tmp_path / "active-results",
            )
    finally:
        active.close()
    assert active_error.value.reason is BacktestFailureReason.SESSION_NOT_REPLAYABLE
    assert bot.start_count == 0

    failed_path = tmp_path / "failed.sqlite3"
    failed = RecordingArchive.create(
        failed_path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(failed)
    _append_trade(failed, START_MS + 10)
    failed.close(clean=False, failure_reason="synthetic failure")
    failed_result = asyncio.run(
        run_backtest(
            BaseBot(),
            _config(),
            bot_spec="tests.test_backtesting:create",
            options=BacktestOptions(
                archive_path=failed_path,
                results_dir=tmp_path / "failed-results",
                report_interval_ms=5,
            ),
        )
    )
    assert failed_result.selection.session_integrity_status is (
        SessionIntegrityStatus.FAILED
    )
    assert failed_result.selection.uses_partial_session is True
    failed_summary = _summary(failed_result.results_dir)
    assert failed_summary["partial"] is False
    assert failed_summary["selection"]["session_integrity_status"] == "failed"
    assert failed_summary["selection"]["uses_partial_session"] is True
    with pytest.raises(BacktestError) as beyond_failure:
        _run(
            BaseBot(),
            _ArchiveWindow(failed_path, START_MS, START_MS + 11),
            tmp_path / "failed-beyond-results",
        )
    assert beyond_failure.value.reason is BacktestFailureReason.INVALID_SELECTION

    ambiguous_path = tmp_path / "ambiguous.sqlite3"
    first = RecordingArchive.create(
        ambiguous_path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(first)
    _append_trade(first, START_MS + 10)
    first.close()
    second = RecordingArchive.resume(
        ambiguous_path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=time.time_ns() // 1_000_000 + 10,
    )
    second.close()
    with pytest.raises(BacktestError) as ambiguous_error:
        asyncio.run(
            run_backtest(
                BaseBot(),
                _config(),
                bot_spec="tests.test_backtesting:create",
                options=BacktestOptions(archive_path=ambiguous_path),
            )
        )
    assert ambiguous_error.value.reason is BacktestFailureReason.INVALID_SELECTION


def test_abandoned_session_is_sealed_and_replays_its_committed_prefix(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "abandoned.sqlite3"
    process_id = os.fork()
    if process_id == 0:
        archive = RecordingArchive.create(
            archive_path,
            target_identity=f"slugs:{MARKET_SLUG}",
            started_at_ms=START_MS,
        )
        _append_prefix(archive)
        _append_trade(archive, START_MS + 10)
        os._exit(17)
    _, status = os.waitpid(process_id, 0)
    assert os.waitstatus_to_exitcode(status) == 17

    result = _run(
        BaseBot(),
        _ArchiveWindow(archive_path, START_MS, START_MS + 10),
        tmp_path / "abandoned-results",
    )

    assert result.selection.end_at_ms == START_MS + 10
    assert result.selection.session_integrity_status is (
        SessionIntegrityStatus.INCOMPLETE
    )
    assert result.selection.uses_partial_session is True
    with RecordingReader(archive_path) as reader:
        (session,) = reader.sessions()
        assert session.ended_at_ms == START_MS + 10
        assert session.clean_close is False
        assert session.integrity_status is SessionIntegrityStatus.INCOMPLETE
        assert session.failure_reason == INTERRUPTED_SESSION_REASON
        assert [event.sequence for event in reader.iter_events()] == [1, 2, 3, 4]
    wal_path = archive_path.with_name(f"{archive_path.name}-wal")
    assert not wal_path.exists() or wal_path.stat().st_size == 0


def test_schema_v1_and_wallet_rules_are_rejected_before_strategy_start(
    tmp_path: Path,
) -> None:
    unsupported = _basic_archive(
        tmp_path,
        name="unsupported.sqlite3",
        tail_offset_ms=10,
    )
    connection = sqlite3.connect(unsupported.path)
    try:
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(BacktestError) as schema_error:
        _run(BaseBot(), unsupported, tmp_path / "unsupported-results")
    assert schema_error.value.reason is BacktestFailureReason.UNSUPPORTED_ARCHIVE

    archive = _basic_archive(
        tmp_path,
        name="wallet.sqlite3",
        tail_offset_ms=10,
    )
    bot = _TrackingBot()
    with pytest.raises(BacktestError) as wallet_error:
        _run(
            bot,
            archive,
            tmp_path / "wallet-results",
            config=_config(wallet_addresses=("0xabc",)),
        )
    assert wallet_error.value.reason is BacktestFailureReason.UNSUPPORTED_INPUT
    assert bot.start_count == 0


def test_gap_missing_baseline_and_missing_midrange_checkpoint_fail_closed(
    tmp_path: Path,
) -> None:
    gap_path = tmp_path / "gap.sqlite3"
    gap_archive = RecordingArchive.create(
        gap_path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(gap_archive)
    gap_start = START_MS + 5
    gap_id = gap_archive.append_gap(
        _event(
            gap_archive,
            CoverageGapPayload(
                reason="disconnect",
                started_at_ms=gap_start,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=gap_start,
            identity=_identity(),
        )
    )
    gap_end = START_MS + 6
    gap_archive.close_gap(gap_id, ended_at_ms=gap_end)
    gap_archive.close()
    with pytest.raises(BacktestError) as gap_error:
        _run(
            BaseBot(),
            _ArchiveWindow(gap_path, START_MS, gap_end),
            tmp_path / "gap-results",
        )
    assert gap_error.value.reason is BacktestFailureReason.COVERAGE_GAP

    baseline_path = tmp_path / "missing-baseline.sqlite3"
    missing_baseline = RecordingArchive.create(
        baseline_path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(missing_baseline, include_down=False)
    _append_trade(missing_baseline, START_MS + 10)
    missing_baseline.close()
    with pytest.raises(BacktestError) as baseline_error:
        _run(
            BaseBot(),
            _ArchiveWindow(baseline_path, START_MS, START_MS + 10),
            tmp_path / "baseline-results",
        )
    assert baseline_error.value.reason is BacktestFailureReason.MISSING_MARKET_DATA

    checkpoint_archive = _basic_archive(
        tmp_path,
        name="missing-checkpoint.sqlite3",
        tail_offset_ms=10,
    )
    with pytest.raises(BacktestError) as checkpoint_error:
        _run(
            BaseBot(),
            checkpoint_archive,
            tmp_path / "checkpoint-results",
            start_ms=START_MS + 5,
        )
    assert checkpoint_error.value.reason is BacktestFailureReason.MISSING_MARKET_DATA


def test_clean_subrange_after_gap_replays_from_common_checkpoint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recovered.sqlite3"
    archive_writer = RecordingArchive.create(
        path,
        target_identity=f"slugs:{MARKET_SLUG}",
        started_at_ms=START_MS,
    )
    _append_prefix(archive_writer)
    gap_start = START_MS + 5
    gap_id = archive_writer.append_gap(
        _event(
            archive_writer,
            CoverageGapPayload(
                reason="disconnect",
                started_at_ms=gap_start,
                ended_at_ms=None,
                affected_condition_ids=(CONDITION_ID,),
                affected_market_slugs=(MARKET_SLUG,),
                affected_token_ids=(UP_TOKEN, DOWN_TOKEN),
            ),
            observed_at_ms=gap_start,
            identity=_identity(),
        )
    )
    archive_writer.close_gap(gap_id, ended_at_ms=START_MS + 6)
    archive_writer.append_event(
        _event(
            archive_writer,
            _baseline(UP_TOKEN),
            observed_at_ms=START_MS + 7,
            identity=_identity(UP_TOKEN),
        )
    )
    archive_writer.append_event(
        _event(
            archive_writer,
            _baseline(DOWN_TOKEN),
            observed_at_ms=START_MS + 8,
            identity=_identity(DOWN_TOKEN),
        )
    )
    checkpoint_sequence = archive_writer.next_sequence - 1
    archive_writer.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=checkpoint_sequence,
                session_id=archive_writer.session_id,
                subscription_generation=1,
                observed_at_ms=START_MS + 8,
                identity=_identity(token_id),
                book=_baseline(token_id),
            )
            for token_id in (UP_TOKEN, DOWN_TOKEN)
        )
    )
    end_ms = START_MS + 10
    _append_trade(archive_writer, end_ms)
    archive_writer.close()
    archive = _ArchiveWindow(path, START_MS, end_ms)
    bot = _TrackingBot()

    result = _run(
        bot,
        archive,
        tmp_path / "results",
        start_ms=START_MS + 9,
    )

    assert result.selection.start_at_ms == START_MS + 9
    assert [book.token_id for book in bot.books] == [UP_TOKEN, DOWN_TOKEN]
    assert _summary(result.results_dir)["status"] == "completed"


def test_clean_multi_market_subrange_uses_each_market_checkpoint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recovered-multi-market.sqlite3"
    archive_writer = RecordingArchive.create(
        path,
        target_identity="bot:tests.test_backtesting:create",
        started_at_ms=START_MS,
    )
    _append_prefix(archive_writer)
    first_checkpoint_sequence = archive_writer.next_sequence - 1
    archive_writer.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=first_checkpoint_sequence,
                session_id=archive_writer.session_id,
                subscription_generation=1,
                observed_at_ms=START_MS + 2,
                identity=_identity(token_id),
                book=_baseline(token_id),
            )
            for token_id in (UP_TOKEN, DOWN_TOKEN)
        )
    )
    archive_writer.append_metadata(
        _event(
            archive_writer,
            _next_metadata(),
            observed_at_ms=START_MS + 3,
            identity=_next_identity(),
        )
    )
    for offset, token_id in enumerate(
        (NEXT_UP_TOKEN, NEXT_DOWN_TOKEN),
        start=4,
    ):
        archive_writer.append_event(
            _event(
                archive_writer,
                _baseline(token_id),
                observed_at_ms=START_MS + offset,
                identity=_next_identity(token_id),
            )
        )
    gap_start = ROLLOVER_MS + 1
    gap_id = archive_writer.append_gap(
        _event(
            archive_writer,
            CoverageGapPayload(
                reason="disconnect",
                started_at_ms=gap_start,
                ended_at_ms=None,
                affected_condition_ids=(NEXT_CONDITION_ID,),
                affected_market_slugs=(NEXT_MARKET_SLUG,),
                affected_token_ids=(NEXT_UP_TOKEN, NEXT_DOWN_TOKEN),
            ),
            observed_at_ms=gap_start,
            identity=_next_identity(),
        )
    )
    archive_writer.close_gap(gap_id, ended_at_ms=ROLLOVER_MS + 2)
    for offset, token_id in enumerate(
        (NEXT_UP_TOKEN, NEXT_DOWN_TOKEN),
        start=3,
    ):
        archive_writer.append_event(
            _event(
                archive_writer,
                _baseline(token_id),
                observed_at_ms=ROLLOVER_MS + offset,
                identity=_next_identity(token_id),
            )
        )
    second_checkpoint_sequence = archive_writer.next_sequence - 1
    archive_writer.append_checkpoints(
        tuple(
            BookCheckpoint(
                sequence=second_checkpoint_sequence,
                session_id=archive_writer.session_id,
                subscription_generation=1,
                observed_at_ms=ROLLOVER_MS + 4,
                identity=_next_identity(token_id),
                book=_baseline(token_id),
            )
            for token_id in (NEXT_UP_TOKEN, NEXT_DOWN_TOKEN)
        )
    )
    replay_start_ms = ROLLOVER_MS + 5
    end_ms = ROLLOVER_MS + 10
    _append_trade(archive_writer, end_ms)
    archive_writer.close()
    bot = _TrackingBot()

    result = _run(
        bot,
        _ArchiveWindow(path, START_MS, end_ms),
        tmp_path / "results",
        config=_config(market_slugs=(MARKET_SLUG, NEXT_MARKET_SLUG)),
        start_ms=replay_start_ms,
    )

    assert result.selection.start_at_ms == replay_start_ms
    assert {book.token_id for book in bot.books} == {
        UP_TOKEN,
        DOWN_TOKEN,
        NEXT_UP_TOKEN,
        NEXT_DOWN_TOKEN,
    }
    assert _summary(result.results_dir)["status"] == "completed"


def test_existing_output_directory_is_refused_and_bot_failure_is_partial(
    tmp_path: Path,
) -> None:
    archive = _basic_archive(tmp_path)
    collision = tmp_path / "collision"
    collision.mkdir()

    with pytest.raises(PerformanceOutputExistsError):
        _run(BaseBot(), archive, collision)

    results_dir = tmp_path / "partial"
    bot = _FailingBot()
    with pytest.raises(RuntimeError, match="strategy exploded"):
        _run(bot, archive, results_dir)

    summary = _summary(results_dir)
    assert summary["status"] == "failed"
    assert summary["partial"] is True
    assert summary["error"] == "RuntimeError: strategy exploded"
    assert (bot.start_count, bot.stop_count) == (1, 1)
