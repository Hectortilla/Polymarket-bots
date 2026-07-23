from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from polymarket.errors import PolymarketError
from polymarket.models.clob.market_events import (
    MarketBookEvent,
    MarketBookPayload,
    MarketLastTradePriceEvent,
    MarketLastTradePricePayload,
    MarketPriceChangeEvent,
    MarketPriceChangePayload,
    MarketResolvedEvent,
    MarketResolvedPayload,
    MarketTickSizeChangeEvent,
    MarketTickSizeChangePayload,
    PriceChange,
)
from polymarket.models.clob.order_book import OrderBookLevel
from polymarket.models.gamma.market import (
    FeeSchedule,
    Market as SdkMarket,
    MarketEvent as SdkMarketEvent,
    MarketOutcome as SdkMarketOutcome,
    MarketOutcomes,
    MarketResolution,
    MarketState,
    MarketTrading,
    UmaResolutionStatus,
)

from polybot.framework.events import Side
from polybot.framework.events.books import BookSnapshot
from polybot.polymarket.errors import (
    MarketDataError,
    MarketDataIssue,
    MarketDataTransportError,
)
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed.capture import (
    MarketCapture,
)
from polybot.polymarket.recording_feed.continuity import (
    CaptureContinuityError,
)
from polybot.polymarket.recording_feed.feed import MarketRecordingFeed
from polybot.polymarket.recording_metadata.contracts import RecordingMarket
from polybot.polymarket.recording_metadata.normalization import (
    normalize_recording_market,
)
from polybot.polymarket.recording_metadata.resolver import RecordingMarketResolver
from polybot.polymarket.markets import Market, MarketOutcome
from polybot.recording.contracts.book import (
    BookBaselinePayload,
    BookDeltaPayload,
    TickSizeChangePayload,
)
from polybot.recording.contracts.anomalies import (
    CaptureFailureKind,
    RevisionFingerprint,
)
from polybot.recording.contracts.payloads import (
    PublicTradePayload,
    ResolutionPayload,
)


class FakeHandle:
    def __init__(self, events: tuple[object, ...], *, dropped: int = 0) -> None:
        self._events = events
        self.dropped = dropped
        self.closed = False

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.closed = True


class FakeStreamClient:
    def __init__(self, handle: FakeHandle) -> None:
        self.handle = handle
        self.specs: list[object] = []

    async def subscribe(self, spec: object) -> FakeHandle:
        self.specs.append(spec)
        return self.handle


def test_capture_preserves_typed_market_events_and_projects_full_depth() -> None:
    timestamps = tuple(datetime.fromtimestamp(value, tz=UTC) for value in range(1, 7))
    events = (
        _book_event(
            "up-token",
            bids=(("0.40", "2"), ("0.50", "1")),
            asks=(("0.70", "3"), ("0.60", "4")),
            source_hash="up-baseline",
            timestamp=timestamps[0],
        ),
        _book_event(
            "down-token",
            bids=(("0.30", "5"),),
            asks=(("0.80", "6"),),
            source_hash="down-baseline",
            timestamp=timestamps[1],
        ),
        MarketPriceChangeEvent(
            type="price_change",
            payload=MarketPriceChangePayload(
                market="condition-bucket",
                price_changes=(
                    PriceChange(
                        asset_id="up-token",
                        price="0.40",
                        size="0",
                        side="BUY",
                        hash="remove-up",
                        best_bid="0",
                        best_ask="0.60",
                    ),
                    PriceChange(
                        asset_id="up-token",
                        price="0.45",
                        size="7.125000",
                        side="BUY",
                        hash="add-up",
                        best_bid="0.45",
                        best_ask="0.60",
                    ),
                    PriceChange(
                        asset_id="down-token",
                        price="0.75",
                        size="8.500",
                        side="SELL",
                        hash="add-down",
                        best_bid="0.30",
                        best_ask="0.75",
                    ),
                ),
                timestamp=timestamps[2],
            ),
        ),
        MarketLastTradePriceEvent(
            type="last_trade_price",
            payload=MarketLastTradePricePayload(
                market="condition-bucket",
                asset_id="up-token",
                price="0.456000",
                size="219.217767",
                side="BUY",
                fee_rate_bps="12.500",
                transaction_hash="0xtrade",
                timestamp=timestamps[3],
            ),
        ),
        MarketTickSizeChangeEvent(
            type="tick_size_change",
            payload=MarketTickSizeChangePayload(
                market="condition-bucket",
                asset_id="up-token",
                old_tick_size="0.01",
                new_tick_size="0.001",
                timestamp=timestamps[4],
            ),
        ),
        MarketResolvedEvent(
            type="market_resolved",
            payload=MarketResolvedPayload(
                id="resolution-1",
                market="condition-bucket",
                token_ids=("up-token", "down-token"),
                winning_token_id="up-token",
                winning_outcome="Up",
                timestamp=timestamps[5],
            ),
        ),
    )
    handle = FakeHandle(events, dropped=2)
    client = FakeStreamClient(handle)

    async def run():
        feed = MarketRecordingFeed(client)  # type: ignore[arg-type]
        capture = await feed.open_capture(_market(), generation=4)
        first = await anext(capture)
        has_complete_baselines_after_first = capture.has_complete_book_baselines
        remaining = [event async for event in capture]
        books = capture.projected_books(9_000)
        diagnostics = capture.diagnostics()
        await capture.close()
        return first, has_complete_baselines_after_first, remaining, books, diagnostics

    (
        first,
        has_complete_baselines_after_first,
        remaining,
        books,
        diagnostics,
    ) = asyncio.run(run())

    assert client.specs[0].token_ids == ("up-token", "down-token")
    assert client.specs[0].custom_feature_enabled is True
    assert has_complete_baselines_after_first is False
    assert isinstance(first.payload, BookBaselinePayload)
    assert first.source_timestamp_ms == 1_000
    assert tuple(level.price for level in first.payload.bids) == (
        Decimal("0.40"),
        Decimal("0.50"),
    )
    assert first.payload.source_hash == "up-baseline"

    delta = remaining[1]
    assert isinstance(delta.payload, BookDeltaPayload)
    assert tuple(change.source_hash for change in delta.payload.changes) == (
        "remove-up",
        "add-up",
        "add-down",
    )
    assert tuple(change.token_id for change in delta.payload.changes) == (
        "up-token",
        "up-token",
        "down-token",
    )
    assert delta.payload.changes[0].size == Decimal("0")
    assert delta.payload.changes[0].best_bid == Decimal("0")
    assert delta.payload.changes[1].size == Decimal("7.125000")

    trade = remaining[2]
    assert trade.payload == PublicTradePayload(
        token_id="up-token",
        price=Decimal("0.456000"),
        size=Decimal("219.217767"),
        side=Side.BUY,
        fee_rate_bps=Decimal("12.500"),
        transaction_hash="0xtrade",
    )
    assert remaining[3].payload == TickSizeChangePayload(
        token_id="up-token",
        old_tick_size=Decimal("0.01"),
        new_tick_size=Decimal("0.001"),
    )
    assert remaining[4].payload == ResolutionPayload(
        token_ids=("up-token", "down-token"),
        winning_token_id="up-token",
        winning_outcome="Up",
        source="market_websocket",
        resolution_id="resolution-1",
    )
    assert [event.source_timestamp_ms for event in remaining] == [
        2_000,
        3_000,
        4_000,
        5_000,
        6_000,
    ]
    assert diagnostics.generation == 4
    assert diagnostics.has_complete_book_baselines is True
    assert diagnostics.dropped_count == 2
    assert diagnostics.baseline_token_ids == {"up-token", "down-token"}
    assert handle.closed is True

    books_by_token = {book.token_id: book for book in books}
    assert tuple(level.price for level in books_by_token["up-token"].bids) == (
        Decimal("0.50"),
        Decimal("0.45"),
    )
    assert tuple(level.price for level in books_by_token["down-token"].asks) == (
        Decimal("0.75"),
        Decimal("0.80"),
    )


def test_capture_combines_split_revision_before_validating_crossed_depth() -> None:
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash="revision-up",
        ),
    )

    async def run():
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        captured = [event async for event in capture]
        books = capture.projected_books(4_000)
        return captured, books

    captured, books = asyncio.run(run())

    assert len(captured) == 3
    combined = captured[-1]
    assert isinstance(combined.payload, BookDeltaPayload)
    assert tuple(
        (change.side, change.price, change.size)
        for change in combined.payload.changes
    ) == (
        (Side.BUY, Decimal("0.55"), Decimal("5")),
        (Side.SELL, Decimal("0.50"), Decimal("0")),
    )
    up_book = next(book for book in books if book.token_id == "up-token")
    assert tuple(level.price for level in up_book.bids) == (
        Decimal("0.55"),
        Decimal("0.40"),
    )
    assert tuple(level.price for level in up_book.asks) == (Decimal("0.60"),)


def test_capture_allows_a_matching_continuation_with_additional_token_hashes() -> None:
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        _multi_price_change_event(
            (
                _price_change(
                    token_id="up-token",
                    price="0.50",
                    size="0",
                    side="SELL",
                    source_hash="revision-up",
                ),
                _price_change(
                    token_id="down-token",
                    price="0.35",
                    size="7",
                    side="BUY",
                    source_hash="revision-down",
                ),
            )
        ),
    )

    async def run() -> tuple[CapturedMarketEvent, tuple[BookSnapshot, ...]]:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        combined = await anext(capture)
        return combined, capture.projected_books(4_000)

    combined, books = asyncio.run(run())

    assert isinstance(combined.payload, BookDeltaPayload)
    assert tuple(change.token_id for change in combined.payload.changes) == (
        "up-token",
        "up-token",
        "down-token",
    )
    books_by_token = {book.token_id: book for book in books}
    assert books_by_token["up-token"].bids[0].price == Decimal("0.55")
    assert books_by_token["up-token"].asks[0].price == Decimal("0.60")
    assert books_by_token["down-token"].bids[0].price == Decimal("0.35")


def test_capture_rejects_crossed_fragments_from_different_revisions() -> None:
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash="different-revision",
        ),
        MarketTickSizeChangeEvent(
            type="tick_size_change",
            payload=MarketTickSizeChangePayload(
                market="condition-bucket",
                asset_id="up-token",
                old_tick_size="0.01",
                new_tick_size="0.001",
                timestamp=datetime.fromtimestamp(4, tz=UTC),
            ),
        ),
    )

    async def run() -> tuple[
        CaptureContinuityError,
        CapturedMarketEvent,
        tuple[BookSnapshot, ...],
    ]:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        next_event = await anext(capture)
        return caught.value, next_event, capture.projected_books(4_000)

    error, next_event, books = asyncio.run(run())

    assert error.issue is MarketDataIssue.CROSSED_BOOK
    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_MISMATCH
    assert error.expected_fingerprint == RevisionFingerprint(
        condition_id="condition-bucket",
        source_timestamp_ms=3_000,
        source_hashes=(("up-token", "revision-up"),),
    )
    assert error.actual_fingerprint == RevisionFingerprint(
        condition_id="condition-bucket",
        source_timestamp_ms=3_000,
        source_hashes=(("up-token", "different-revision"),),
    )
    assert error.matching_fragments == ()
    assert error.mismatching_fragment is error.fragments[-1]
    assert isinstance(error.mismatching_fragment.payload, BookDeltaPayload)
    assert (
        error.mismatching_fragment.payload.changes[0].source_hash
        == "different-revision"
    )
    assert error.mismatching_fragment.payload.changes[0].best_bid == Decimal("0.55")
    assert error.dropped_count_before == 0
    assert error.dropped_count_after == 0
    assert error.elapsed_seconds >= 0
    assert isinstance(next_event.payload, TickSizeChangePayload)
    up_book = next(book for book in books if book.token_id == "up-token")
    assert up_book.bids[0].price == Decimal("0.40")
    assert up_book.asks[0].price == Decimal("0.50")


@pytest.mark.parametrize("mismatch", ("timestamp", "missing_hash", "unrelated"))
def test_capture_rejects_unprovable_split_revision_continuations(
    mismatch: str,
) -> None:
    if mismatch == "timestamp":
        continuation: object = _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash="revision-up",
            timestamp_seconds=4,
        )
    elif mismatch == "missing_hash":
        continuation = _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash=None,
        )
    else:
        continuation = MarketLastTradePriceEvent(
            type="last_trade_price",
            payload=MarketLastTradePricePayload(
                market="condition-bucket",
                asset_id="up-token",
                price="0.45",
                size="1",
                side="BUY",
                timestamp=datetime.fromtimestamp(3, tz=UTC),
            ),
        )
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        continuation,
    )

    async def run() -> CaptureContinuityError:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_MISMATCH
    assert error.mismatching_fragment is not None
    if mismatch == "timestamp":
        assert error.actual_fingerprint is not None
        assert error.actual_fingerprint.source_timestamp_ms == 4_000
    else:
        assert error.actual_fingerprint is None


def test_capture_rejects_an_unsupported_event_between_split_fragments() -> None:
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        object(),
        _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash="revision-up",
        ),
    )

    async def run() -> CaptureContinuityError:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_MISMATCH
    assert error.matching_fragments == ()
    assert error.mismatching_fragment is None
    assert error.actual_fingerprint is None


def test_capture_allows_a_later_fragment_to_omit_an_added_token_hash() -> None:
    events = _split_revision_with_added_hash(
        (
            _price_change(
                token_id="up-token",
                price="0.50",
                size="0",
                side="SELL",
                source_hash="revision-up",
            ),
        )
    )

    async def run() -> CapturedMarketEvent:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        return await anext(capture)

    combined = asyncio.run(run())

    assert isinstance(combined.payload, BookDeltaPayload)
    assert tuple(change.token_id for change in combined.payload.changes) == (
        "up-token",
        "up-token",
        "down-token",
        "up-token",
    )


def test_capture_rejects_a_changed_previously_added_token_hash() -> None:
    events = _split_revision_with_added_hash(
        (
            _price_change(
                token_id="up-token",
                price="0.50",
                size="0",
                side="SELL",
                source_hash="revision-up",
            ),
            _price_change(
                token_id="down-token",
                price="0.36",
                size="1",
                side="BUY",
                source_hash="changed-down",
            ),
        )
    )

    async def run() -> CaptureContinuityError:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_MISMATCH
    assert len(error.matching_fragments) == 1
    assert error.expected_fingerprint == RevisionFingerprint(
        condition_id="condition-bucket",
        source_timestamp_ms=3_000,
        source_hashes=(
            ("up-token", "revision-up"),
            ("down-token", "revision-down"),
        ),
    )
    assert error.mismatching_fragment is not None


def test_capture_rejects_a_crossed_first_fragment_without_a_hash() -> None:
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash=None,
        ),
    )

    async def run() -> CaptureContinuityError:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_MISMATCH
    assert error.expected_fingerprint is None
    assert error.mismatching_fragment is None
    assert len(error.fragments) == 1


def test_capture_times_out_an_unfinished_split_revision() -> None:
    class HangingHandle:
        dropped = 0

        def __init__(self) -> None:
            self.closed = False

        def __aiter__(self) -> AsyncIterator[object]:
            return self._iterate()

        async def _iterate(self) -> AsyncIterator[object]:
            for event in _split_revision_prefix():
                yield event
            yield _price_change_event(
                price="0.55",
                size="5",
                side="BUY",
                source_hash="revision-up",
            )
            await asyncio.Event().wait()

        async def close(self) -> None:
            self.closed = True

    async def run() -> CaptureContinuityError:
        capture = MarketCapture(
            HangingHandle(),
            market=_market(),
            generation=7,
            split_revision_timeout_seconds=0.01,
        )
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.issue is MarketDataIssue.CROSSED_BOOK
    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_TIMEOUT
    assert error.mismatching_fragment is None


def test_capture_reports_an_ended_split_revision() -> None:
    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
    )

    async def run() -> CaptureContinuityError:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SPLIT_REVISION_END
    assert error.expected_fingerprint is not None


@pytest.mark.parametrize("drop_event_index", (2, 3))
def test_capture_detects_sdk_drops_during_split_revision_assembly(
    drop_event_index: int,
) -> None:
    class DroppingHandle(FakeHandle):
        async def _iterate(self) -> AsyncIterator[object]:
            for index, event in enumerate(self._events):
                if index == drop_event_index:
                    self.dropped += 1
                yield event

    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash="revision-up",
        ),
    )

    async def run() -> CaptureContinuityError:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(DroppingHandle(events))
        ).open_capture(_market(), generation=7)
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value

    error = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SDK_HANDLE_DROP
    assert error.dropped_count_before == 0
    assert error.dropped_count_after == 1
    expected_fragment_count = 1 if drop_event_index == 2 else 2
    assert len(error.fragments) == expected_fragment_count


def test_capture_checks_sdk_drops_immediately_before_revision_commit() -> None:
    class CommitDropHandle:
        def __init__(self, events: tuple[object, ...]) -> None:
            self._events = events
            self._continuation_delivered = False
            self._post_continuation_drop_reads = 0
            self.closed = False

        @property
        def dropped(self) -> int:
            if not self._continuation_delivered:
                return 0
            self._post_continuation_drop_reads += 1
            return int(self._post_continuation_drop_reads >= 2)

        def __aiter__(self) -> AsyncIterator[object]:
            return self._iterate()

        async def _iterate(self) -> AsyncIterator[object]:
            for index, event in enumerate(self._events):
                if index == 3:
                    self._continuation_delivered = True
                yield event

        async def close(self) -> None:
            self.closed = True

    events = _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        _price_change_event(
            price="0.50",
            size="0",
            side="SELL",
            source_hash="revision-up",
        ),
    )

    async def run() -> tuple[CaptureContinuityError, tuple[BookSnapshot, ...]]:
        capture = MarketCapture(
            CommitDropHandle(events),
            market=_market(),
            generation=7,
        )
        await anext(capture)
        await anext(capture)
        with pytest.raises(CaptureContinuityError) as caught:
            await anext(capture)
        return caught.value, capture.projected_books(4_000)

    error, books = asyncio.run(run())

    assert error.failure_kind is CaptureFailureKind.SDK_HANDLE_DROP
    up_book = next(book for book in books if book.token_id == "up-token")
    assert up_book.bids[0].price == Decimal("0.40")
    assert up_book.asks[0].price == Decimal("0.50")


def test_capture_rejects_delta_before_baseline() -> None:
    delta = MarketPriceChangeEvent(
        type="price_change",
        payload=MarketPriceChangePayload(
            market="condition-bucket",
            price_changes=(
                PriceChange(
                    asset_id="up-token",
                    price="0.40",
                    size="1",
                    side="BUY",
                ),
            ),
        ),
    )

    async def run() -> MarketDataIssue:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle((delta,)))
        ).open_capture(_market(), generation=0)
        with pytest.raises(MarketDataError) as caught:
            await anext(capture)
        return caught.value.issue

    assert asyncio.run(run()) is MarketDataIssue.MISSING_BOOK_BASELINE


def test_capture_rejects_mismatched_book_identity() -> None:
    mismatched = _book_event(
        "up-token",
        condition_id="condition-other",
        bids=(("0.40", "2"),),
        asks=(("0.60", "2"),),
    )

    async def run() -> MarketDataIssue:
        capture = await MarketRecordingFeed(  # type: ignore[arg-type]
            FakeStreamClient(FakeHandle((mismatched,)))
        ).open_capture(_market(), generation=0)
        with pytest.raises(MarketDataError) as caught:
            await anext(capture)
        return caught.value.issue

    assert asyncio.run(run()) is MarketDataIssue.BOOK_IDENTITY_MISMATCH


def test_recording_metadata_preserves_rich_gamma_fields() -> None:
    resolved = normalize_recording_market(_sdk_market("resolved", resolved=True))

    assert resolved.market.resolved is True
    assert resolved.metadata.market_id == "market-resolved"
    assert resolved.metadata.events[0].event_id == "event-resolved"
    assert resolved.metadata.events[0].slug == "event-slug-resolved"
    assert resolved.metadata.outcomes[0].label == "Up"
    assert resolved.metadata.outcomes[0].price == Decimal("1")
    assert resolved.metadata.start_at_ms == 1_000
    assert resolved.metadata.end_at_ms == 2_000
    assert resolved.metadata.closed_at_ms == 3_000
    assert resolved.metadata.order_book_enabled is True
    assert resolved.metadata.accepting_orders is False
    assert resolved.metadata.minimum_tick_size == Decimal("0.001")
    assert resolved.metadata.minimum_order_size == Decimal("5.500")
    assert resolved.metadata.seconds_delay == 3
    assert resolved.metadata.neg_risk is True
    assert resolved.metadata.fees_enabled is True
    assert resolved.metadata.fee_type == "curve"
    assert resolved.metadata.fee_schedule is not None
    assert resolved.metadata.fee_schedule.exponent == Decimal("2")
    assert resolved.metadata.fee_schedule.rate == Decimal("0.0250")
    assert resolved.metadata.fee_schedule.rebate_rate == Decimal("0.005")
    assert resolved.metadata.question_id == "question-resolved"
    assert resolved.metadata.neg_risk_request_id == "request-resolved"
    assert resolved.metadata.resolution_status == "settled"
    assert resolved.metadata.resolution_source == "official source"
    assert resolved.metadata.resolved_by == "0xresolver"
    assert resolved.metadata.winning_token_id == "up-token"
    assert resolved.metadata.winning_outcome == "Up"


def test_recording_market_resolver_keeps_order_and_missing_entries() -> None:
    source = _sdk_market("alpha")

    class Paginator:
        def __init__(self, include_source: bool) -> None:
            self.include_source = include_source

        def iter_items(self) -> AsyncIterator[SdkMarket]:
            async def iterate() -> AsyncIterator[SdkMarket]:
                if self.include_source:
                    yield source

            return iterate()

    class Client:
        def list_markets(self, **kwargs: object) -> Paginator:
            requested = kwargs.get("slug", ())
            return Paginator(
                isinstance(requested, tuple) and "alpha" in requested
            )

    async def run() -> tuple[RecordingMarket | None, ...]:
        resolver = RecordingMarketResolver(Client())  # type: ignore[arg-type]
        return await resolver.find_many(
            ("alpha", "missing", "alpha")
        )

    results = asyncio.run(run())

    assert results[0] is not None
    assert results[0] == results[2]
    assert results[1] is None
    assert results[0].metadata.market_slug == "alpha"


def test_recording_market_resolver_rejects_mismatched_slug_response() -> None:
    class Client:
        async def get_market(self, *, slug: str) -> SdkMarket:
            assert slug == "requested"
            return _sdk_market("different")

    async def run() -> MarketDataIssue:
        resolver = RecordingMarketResolver(Client())  # type: ignore[arg-type]
        with pytest.raises(MarketDataError) as caught:
            await resolver.find_by_slug("requested")
        return caught.value.issue

    assert asyncio.run(run()) is MarketDataIssue.AMBIGUOUS_MARKET_METADATA


def test_recording_market_resolver_normalizes_sdk_lookup_failures() -> None:
    class Client:
        async def get_market(self, *, slug: str) -> SdkMarket:
            del slug
            raise PolymarketError("Gamma unavailable")

    async def run() -> MarketDataTransportError:
        resolver = RecordingMarketResolver(Client())  # type: ignore[arg-type]
        with pytest.raises(MarketDataTransportError) as caught:
            await resolver.find_by_slug("requested")
        return caught.value

    error = asyncio.run(run())

    assert str(error) == "Gamma recording-market lookup failed"
    assert isinstance(error.__cause__, PolymarketError)


def test_recording_feed_normalizes_sdk_subscription_failures() -> None:
    class Client:
        async def subscribe(self, spec: object) -> FakeHandle:
            del spec
            raise PolymarketError("stream unavailable")

    async def run() -> MarketDataTransportError:
        feed = MarketRecordingFeed(Client())  # type: ignore[arg-type]
        with pytest.raises(MarketDataTransportError) as caught:
            await feed.open_capture(_market(), generation=1)
        return caught.value

    error = asyncio.run(run())

    assert str(error) == "recording market subscription failed"
    assert isinstance(error.__cause__, PolymarketError)


@pytest.mark.parametrize("failure_stage", ("read", "close"))
def test_market_capture_normalizes_sdk_handle_failures(
    failure_stage: str,
) -> None:
    class FailingHandle:
        def __aiter__(self) -> AsyncIterator[object]:
            return self._events()

        async def _events(self) -> AsyncIterator[object]:
            if failure_stage == "read":
                raise PolymarketError("capture unavailable")
            return
            yield None

        async def close(self) -> None:
            if failure_stage == "close":
                raise PolymarketError("capture shutdown unavailable")

    async def run() -> MarketDataTransportError:
        capture = MarketCapture(FailingHandle(), market=_market(), generation=1)
        with pytest.raises(MarketDataTransportError) as caught:
            if failure_stage == "read":
                await anext(capture)
            else:
                await capture.close()
        return caught.value

    error = asyncio.run(run())

    expected_message = (
        "recording market capture failed"
        if failure_stage == "read"
        else "recording market capture shutdown failed"
    )
    assert str(error) == expected_message
    assert isinstance(error.__cause__, PolymarketError)


def _market() -> Market:
    return Market(
        condition_id="condition-bucket",
        slug="bucket",
        question="Will it go up?",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0.02"),
        outcomes=(
            MarketOutcome("Up", "up-token"),
            MarketOutcome("Down", "down-token"),
        ),
    )


def _book_event(
    token_id: str,
    *,
    condition_id: str = "condition-bucket",
    bids: tuple[tuple[str, str], ...],
    asks: tuple[tuple[str, str], ...],
    source_hash: str | None = None,
    timestamp: datetime | None = None,
) -> MarketBookEvent:
    return MarketBookEvent(
        type="book",
        payload=MarketBookPayload(
            market=condition_id,
            asset_id=token_id,
            bids=tuple(OrderBookLevel(price=price, size=size) for price, size in bids),
            asks=tuple(OrderBookLevel(price=price, size=size) for price, size in asks),
            hash=source_hash,
            timestamp=timestamp,
        ),
    )


def _split_revision_prefix() -> tuple[MarketBookEvent, MarketBookEvent]:
    return (
        _book_event(
            "up-token",
            bids=(("0.40", "2"),),
            asks=(("0.50", "3"), ("0.60", "4")),
            timestamp=datetime.fromtimestamp(1, tz=UTC),
        ),
        _book_event(
            "down-token",
            bids=(("0.30", "5"),),
            asks=(("0.70", "6"),),
            timestamp=datetime.fromtimestamp(2, tz=UTC),
        ),
    )


def _split_revision_with_added_hash(
    third_changes: tuple[PriceChange, ...],
) -> tuple[object, ...]:
    return _split_revision_prefix() + (
        _price_change_event(
            price="0.55",
            size="5",
            side="BUY",
            source_hash="revision-up",
        ),
        _multi_price_change_event(
            (
                _price_change(
                    token_id="up-token",
                    price="0.56",
                    size="2",
                    side="BUY",
                    source_hash="revision-up",
                ),
                _price_change(
                    token_id="down-token",
                    price="0.35",
                    size="7",
                    side="BUY",
                    source_hash="revision-down",
                ),
            )
        ),
        _multi_price_change_event(third_changes),
    )


def _price_change_event(
    *,
    price: str,
    size: str,
    side: str,
    source_hash: str | None,
    timestamp_seconds: int = 3,
) -> MarketPriceChangeEvent:
    return _multi_price_change_event(
        (
            _price_change(
                token_id="up-token",
                price=price,
                size=size,
                side=side,
                source_hash=source_hash,
            ),
        ),
        timestamp_seconds=timestamp_seconds,
    )


def _multi_price_change_event(
    changes: tuple[PriceChange, ...],
    *,
    timestamp_seconds: int = 3,
) -> MarketPriceChangeEvent:
    return MarketPriceChangeEvent(
        type="price_change",
        payload=MarketPriceChangePayload(
            market="condition-bucket",
            price_changes=changes,
            timestamp=datetime.fromtimestamp(timestamp_seconds, tz=UTC),
        ),
    )


def _price_change(
    *,
    token_id: str,
    price: str,
    size: str,
    side: str,
    source_hash: str | None,
) -> PriceChange:
    return PriceChange(
        asset_id=token_id,
        price=price,
        size=size,
        side=side,
        hash=source_hash,
        best_bid="0.55",
        best_ask="0.60",
    )


def _sdk_market(slug: str, *, resolved: bool = False) -> SdkMarket:
    first_price = Decimal("1") if resolved else Decimal("0.45")
    second_price = Decimal("0") if resolved else Decimal("0.55")
    return SdkMarket.model_construct(
        id=f"market-{slug}",
        slug=slug,
        condition_id=f"condition-{slug}",
        question=f"Question {slug}?",
        state=MarketState(
            active=not resolved,
            closed=resolved,
            archived=False,
            acceptingOrders=not resolved,
            enableOrderBook=True,
            negRisk=True,
            startDate=datetime.fromtimestamp(1, tz=UTC),
            endDate=datetime.fromtimestamp(2, tz=UTC),
            closedTime=datetime.fromtimestamp(3, tz=UTC) if resolved else None,
        ),
        outcomes=MarketOutcomes(
            yes=SdkMarketOutcome(
                label="Up",
                tokenId="up-token",
                price=first_price,
            ),
            no=SdkMarketOutcome(
                label="Down",
                tokenId="down-token",
                price=second_price,
            ),
        ),
        trading=MarketTrading(
            minimumOrderSize="5.500",
            minimumTickSize="0.001",
            secondsDelay=3,
            feesEnabled=True,
            feeType="curve",
            feeSchedule=FeeSchedule(
                exponent=2,
                rate=Decimal("0.0250"),
                takerOnly=True,
                rebateRate=Decimal("0.005"),
            ),
        ),
        resolution=MarketResolution.model_construct(
            question_id=f"question-{slug}",
            neg_risk_request_id=f"request-{slug}",
            uma_resolution_status=(
                UmaResolutionStatus.SETTLED
                if resolved
                else UmaResolutionStatus.PROPOSED
            ),
            source="official source",
            resolved_by="0xresolver",
        ),
        events=(
            SdkMarketEvent(
                id=f"event-{slug}",
                slug=f"event-slug-{slug}",
                title=f"Event {slug}",
            ),
        ),
    )
