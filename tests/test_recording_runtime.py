from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from polybot.framework.config.models import BotConfig
from polybot.framework.events import Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.framework.streams import StreamPlan, StreamRelation, StreamRule
from polybot.polymarket.errors import MarketDataError, MarketDataIssue
from polybot.polymarket.recording_events import CapturedMarketEvent
from polybot.polymarket.recording_feed import CaptureContinuityError
from polybot.polymarket.recording_metadata import RecordingMarket
from polybot.polymarket.types import Market, MarketOutcome
from polybot.recording import entrypoint
from polybot.recording.archive import (
    ArchiveExistsError,
    RecordingArchive,
    RecordingReader,
)
from polybot.recording.contracts import (
    BookBaselinePayload,
    BookChange,
    BookCheckpoint,
    BookDeltaPayload,
    CaptureAnomalyPayload,
    CaptureAnomalyRecord,
    CaptureFailureKind,
    CaptureFragmentRole,
    CoverageGapPayload,
    MarketIdentity,
    MarketMetadataPayload,
    MarketOutcomeMetadata,
    PublicTradePayload,
    RecordedBookLevel,
    RecordedEvent,
    RevisionFingerprint,
    ResolutionPayload,
    SessionIntegrityStatus,
    TickSizeChangePayload,
)
from polybot.recording.coordinator import (
    RecordingCoordinator,
    _capture_anomaly_payload,
)
from polybot.recording.service import (
    CANCELLED_RECORDING_REASON,
    _finish_recording,
    _read_resume_state,
    _resolve_initial_markets,
    record_markets,
)
from polybot.recording.writer import (
    AsyncRecordingWriter,
    OpenedCoverageGap,
    PendingRecordingEvent,
    RecordingCheckpointWrite,
    RecordingEventWrite,
    RecordingWriteError,
    RecordingWriteQueueFullError,
)


class StepClock:
    def __init__(self, start: int = 1_000) -> None:
        self._now = start

    def now_ms(self) -> int:
        self._now += 1
        return self._now


class MutablePlanProvider:
    def __init__(self, plan: StreamPlan) -> None:
        self.current_plan = plan
        self.calls: list[int] = []

    async def plan(self, now_ms: int) -> StreamPlan:
        self.calls.append(now_ms)
        return self.current_plan


class MutableResolver:
    def __init__(
        self,
        markets: dict[str, RecordingMarket | None],
    ) -> None:
        self.markets = markets
        self.calls: list[tuple[str, ...]] = []
        self.closed = False

    async def find_many(
        self,
        slugs: Iterable[str],
    ) -> tuple[RecordingMarket | None, ...]:
        requested = tuple(slugs)
        self.calls.append(requested)
        return tuple(self.markets.get(slug) for slug in requested)

    async def close(self) -> None:
        self.closed = True


_CAPTURE_END = object()


class FakeCapture:
    def __init__(
        self,
        market: Market,
        generation: int,
        operations: list[str],
    ) -> None:
        self.market = market
        self.generation = generation
        self.dropped_count = 0
        self.closed = False
        self._operations = operations
        self._queue: asyncio.Queue[CapturedMarketEvent | BaseException | object] = (
            asyncio.Queue()
        )
        self._books: dict[str, BookSnapshot] = {}

    @property
    def ready(self) -> bool:
        return set(self.market.token_ids) <= self._books.keys()

    def __aiter__(self) -> FakeCapture:
        return self

    async def __anext__(self) -> CapturedMarketEvent:
        item = await self._queue.get()
        if item is _CAPTURE_END:
            raise StopAsyncIteration
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, CapturedMarketEvent)
        if isinstance(item.payload, BookBaselinePayload):
            self._books[item.payload.token_id] = BookSnapshot(
                token_id=item.payload.token_id,
                bids=tuple(
                    BookLevel(level.price, level.size)
                    for level in item.payload.bids
                ),
                asks=tuple(
                    BookLevel(level.price, level.size)
                    for level in item.payload.asks
                ),
                received_at_ms=item.source_timestamp_ms or 0,
                market_slug=self.market.slug,
                condition_id=self.market.condition_id,
                outcome=next(
                    outcome.label
                    for outcome in self.market.outcomes
                    if outcome.token_id == item.payload.token_id
                ),
            )
        return item

    async def emit(self, event: CapturedMarketEvent) -> None:
        await self._queue.put(event)

    async def fail(self, error: BaseException) -> None:
        await self._queue.put(error)

    def projected_books(self, observed_at_ms: int) -> tuple[BookSnapshot, ...]:
        return tuple(
            BookSnapshot(
                token_id=book.token_id,
                bids=book.bids,
                asks=book.asks,
                received_at_ms=observed_at_ms,
                market_slug=book.market_slug,
                condition_id=book.condition_id,
                outcome=book.outcome,
            )
            for book in self._books.values()
        )

    def project_unrecorded_bid(self, token_id: str, price: Decimal) -> None:
        book = self._books[token_id]
        self._books[token_id] = BookSnapshot(
            token_id=book.token_id,
            bids=(BookLevel(price, Decimal("99")),),
            asks=book.asks,
            received_at_ms=book.received_at_ms,
            market_slug=book.market_slug,
            condition_id=book.condition_id,
            outcome=book.outcome,
        )

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._operations.append(f"close:{self.market.condition_id}:{self.generation}")


class FakeFeed:
    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.captures: list[FakeCapture] = []
        self.closed = False

    async def open_capture(
        self,
        market: Market,
        *,
        generation: int,
    ) -> FakeCapture:
        capture = FakeCapture(market, generation, self.operations)
        self.captures.append(capture)
        self.operations.append(f"open:{market.condition_id}:{generation}")
        return capture

    async def close(self) -> None:
        self.closed = True

    def latest(self, condition_id: str) -> FakeCapture:
        return next(
            capture
            for capture in reversed(self.captures)
            if capture.market.condition_id == condition_id
        )


class MemoryWriter:
    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.events: list[RecordedEvent] = []
        self.anomalies: list[CaptureAnomalyRecord] = []
        self.checkpoints: list[BookCheckpoint] = []
        self.closed_gaps: list[tuple[int, int]] = []
        self.failure: BaseException | None = None
        self.session_id = 1
        self._next_sequence = 1
        self._next_gap_id = 1
        self._next_anomaly_id = 1

    async def record(
        self,
        payload: object,
        *,
        observed_at_ms: int,
        source_timestamp_ms: int | None,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> RecordedEvent:
        return await self.enqueue_record(
            payload,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=source_timestamp_ms,
            identity=identity,
            subscription_generation=subscription_generation,
        ).wait()

    def enqueue_record(
        self,
        payload: object,
        *,
        observed_at_ms: int,
        source_timestamp_ms: int | None,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> PendingRecordingEvent:
        event = self._record_now(
            payload,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=source_timestamp_ms,
            identity=identity,
            subscription_generation=subscription_generation,
        )
        completion = asyncio.get_running_loop().create_future()
        completion.set_result(None)
        return PendingRecordingEvent(event, completion)

    def _record_now(
        self,
        payload: object,
        *,
        observed_at_ms: int,
        source_timestamp_ms: int | None,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> RecordedEvent:
        event = RecordedEvent(
            sequence=self._next_sequence,
            session_id=self.session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=source_timestamp_ms,
            identity=identity,
            payload=payload,  # type: ignore[arg-type]
        )
        self._next_sequence += 1
        self.events.append(event)
        self.operations.append(f"record:{type(payload).__name__}")
        return event

    async def record_batch(
        self,
        writes: tuple[RecordingEventWrite, ...],
    ) -> tuple[RecordedEvent, ...]:
        return tuple(
            [
                await self.record(
                    write.payload,
                    observed_at_ms=write.observed_at_ms,
                    source_timestamp_ms=write.source_timestamp_ms,
                    identity=write.identity,
                    subscription_generation=write.subscription_generation,
                )
                for write in writes
            ]
        )

    async def open_gap(
        self,
        payload: CoverageGapPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity | None,
        subscription_generation: int,
    ) -> OpenedCoverageGap:
        event = await self.record(
            payload,
            observed_at_ms=observed_at_ms,
            source_timestamp_ms=None,
            identity=identity,
            subscription_generation=subscription_generation,
        )
        gap_id = self._next_gap_id
        self._next_gap_id += 1
        return OpenedCoverageGap(gap_id=gap_id, event=event)

    async def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        self.closed_gaps.append((gap_id, ended_at_ms))
        self.operations.append(f"close-gap:{gap_id}")

    async def record_anomaly(
        self,
        anomaly: CaptureAnomalyPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> CaptureAnomalyRecord:
        record = CaptureAnomalyRecord(
            anomaly_id=self._next_anomaly_id,
            session_id=self.session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            identity=identity,
            anomaly=anomaly,
        )
        self._next_anomaly_id += 1
        self.anomalies.append(record)
        self.operations.append(f"anomaly:{anomaly.failure_kind.value}")
        return record

    async def checkpoint(
        self,
        book: BookBaselinePayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> BookCheckpoint:
        checkpoint = BookCheckpoint(
            sequence=self._next_sequence - 1,
            session_id=self.session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            identity=identity,
            book=book,
        )
        self.checkpoints.append(checkpoint)
        self.operations.append(f"checkpoint:{book.token_id}")
        return checkpoint

    async def checkpoint_batch(
        self,
        writes: tuple[RecordingCheckpointWrite, ...],
    ) -> tuple[BookCheckpoint, ...]:
        return tuple(
            [
                await self.checkpoint(
                    write.book,
                    observed_at_ms=write.observed_at_ms,
                    identity=write.identity,
                    subscription_generation=write.subscription_generation,
                )
                for write in writes
            ]
        )


class MemoryArchive:
    def __init__(self) -> None:
        self.next_sequence = 1
        self.session_id = 1
        self.events: list[RecordedEvent] = []
        self.event_batches: list[tuple[RecordedEvent, ...]] = []
        self.checkpoints: list[BookCheckpoint] = []
        self.checkpoint_batches: list[tuple[BookCheckpoint, ...]] = []
        self.closed_gaps: list[tuple[int, int]] = []
        self.close_calls: list[tuple[bool, str | None]] = []

    def append_events(self, events: Iterable[RecordedEvent]) -> None:
        batch = tuple(events)
        self.event_batches.append(batch)
        self.events.extend(batch)

    def append_checkpoint(self, checkpoint: BookCheckpoint) -> None:
        self.checkpoints.append(checkpoint)

    def append_checkpoints(self, checkpoints: Iterable[BookCheckpoint]) -> None:
        batch = tuple(checkpoints)
        self.checkpoint_batches.append(batch)
        self.checkpoints.extend(batch)

    def append_gap(self, event: RecordedEvent) -> int:
        self.append_events((event,))
        return event.sequence

    def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        self.closed_gaps.append((gap_id, ended_at_ms))

    def close(self, *, clean: bool, failure_reason: str | None) -> None:
        self.close_calls.append((clean, failure_reason))


class BlockingArchive(MemoryArchive):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def append_events(self, events: Iterable[RecordedEvent]) -> None:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test archive was not released")
        super().append_events(events)


class BlockingCheckpointArchive(MemoryArchive):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def append_checkpoints(self, checkpoints: Iterable[BookCheckpoint]) -> None:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test checkpoint archive was not released")
        super().append_checkpoints(checkpoints)


class BlockingMutationArchive(MemoryArchive):
    def __init__(self, operation: str) -> None:
        super().__init__()
        self.operation = operation
        self.started = threading.Event()
        self.release = threading.Event()

    def _block(self, operation: str) -> None:
        if self.operation != operation:
            return
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test archive mutation was not released")

    def append_gap(self, event: RecordedEvent) -> int:
        self._block("open_gap")
        return super().append_gap(event)

    def close_gap(self, gap_id: int, *, ended_at_ms: int) -> None:
        self._block("close_gap")
        super().close_gap(gap_id, ended_at_ms=ended_at_ms)

    def append_capture_anomaly(
        self,
        anomaly: CaptureAnomalyPayload,
        *,
        observed_at_ms: int,
        identity: MarketIdentity,
        subscription_generation: int,
    ) -> CaptureAnomalyRecord:
        self._block("anomaly")
        return CaptureAnomalyRecord(
            anomaly_id=1,
            session_id=self.session_id,
            subscription_generation=subscription_generation,
            observed_at_ms=observed_at_ms,
            identity=identity,
            anomaly=anomaly,
        )


class FailingArchive(MemoryArchive):
    def append_events(self, events: Iterable[RecordedEvent]) -> None:
        raise OSError("disk failed")


class BlockingFailingArchive(BlockingArchive):
    def append_events(self, events: Iterable[RecordedEvent]) -> None:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test archive was not released")
        raise OSError("disk failed")


def test_writer_preserves_global_multi_market_order_without_coalescing() -> None:
    async def run() -> tuple[list[RecordedEvent], list[tuple[RecordedEvent, ...]]]:
        archive = MemoryArchive()
        writer = AsyncRecordingWriter(archive, batch_size=16)  # type: ignore[arg-type]
        for token_id, timestamp in (
            ("alpha-up", 10),
            ("beta-down", 11),
            ("alpha-up", 12),
        ):
            await writer.record(
                _baseline_payload(token_id),
                observed_at_ms=timestamp,
                source_timestamp_ms=timestamp - 1,
                identity=MarketIdentity(
                    condition_id=token_id.split("-", 1)[0],
                    market_slug=token_id.split("-", 1)[0],
                    token_id=token_id,
                ),
                subscription_generation=1,
            )
        await writer.flush()
        await writer.stop(clean=True)
        return archive.events, archive.event_batches

    events, batches = asyncio.run(run())

    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.payload.token_id for event in events] == [
        "alpha-up",
        "beta-down",
        "alpha-up",
    ]
    assert sum(len(batch) for batch in batches) == 3


@pytest.mark.parametrize(
    "payload_kind",
    ("metadata", "book", "book_delta", "trade", "tick_change", "resolution"),
)
def test_recorded_payloads_do_not_acknowledge_before_commit_returns(
    payload_kind: str,
) -> None:
    async def run() -> tuple[bool, list[RecordedEvent]]:
        archive = BlockingArchive()
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        recording = _recording_market("alpha")
        token_id = recording.market.token_ids[0]
        payloads = {
            "metadata": recording.metadata,
            "book": _baseline_payload(token_id),
            "book_delta": BookDeltaPayload(
                changes=(
                    BookChange(
                        token_id,
                        Side.BUY,
                        Decimal("0.40"),
                        Decimal("2"),
                    ),
                )
            ),
            "trade": PublicTradePayload(
                token_id,
                Decimal("0.40"),
                Decimal("2"),
                Side.BUY,
            ),
            "tick_change": TickSizeChangePayload(
                token_id,
                Decimal("0.01"),
                Decimal("0.001"),
            ),
            "resolution": ResolutionPayload(
                recording.market.token_ids,
                token_id,
                recording.market.outcomes[0].label,
                "market_websocket",
            ),
        }
        payload = payloads[payload_kind]
        write = asyncio.create_task(
            writer.record(
                payload,
                observed_at_ms=10,
                source_timestamp_ms=9,
                identity=MarketIdentity(
                    recording.market.condition_id,
                    recording.market.slug,
                    (
                        None
                        if payload_kind in {"metadata", "resolution"}
                        else token_id
                    ),
                ),
                subscription_generation=1,
            )
        )
        await _wait_for(archive.started.is_set)
        acknowledged_while_blocked = write.done()
        archive.release.set()
        await write
        await writer.stop(clean=True)
        return acknowledged_while_blocked, archive.events

    acknowledged_while_blocked, events = asyncio.run(run())

    assert acknowledged_while_blocked is False
    assert [event.sequence for event in events] == [1]
    assert events[0].payload is not None


def test_enqueued_record_exposes_no_durable_ack_before_commit() -> None:
    async def run() -> tuple[bool, int]:
        archive = BlockingArchive()
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        pending = writer.enqueue_record(
            _baseline_payload("alpha-up"),
            observed_at_ms=10,
            source_timestamp_ms=9,
            identity=MarketIdentity("alpha", "alpha", "alpha-up"),
            subscription_generation=1,
        )
        await _wait_for(archive.started.is_set)
        completed_while_blocked = pending.done
        archive.release.set()
        event = await pending.wait()
        await writer.stop(clean=True)
        return completed_while_blocked, event.sequence

    completed_while_blocked, sequence = asyncio.run(run())

    assert completed_while_blocked is False
    assert sequence == 1


def test_checkpoint_does_not_acknowledge_before_commit_returns() -> None:
    async def run() -> tuple[bool, list[BookCheckpoint]]:
        archive = BlockingCheckpointArchive()
        archive.next_sequence = 2
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        write = asyncio.create_task(
            writer.checkpoint(
                _baseline_payload("alpha-up"),
                observed_at_ms=10,
                identity=MarketIdentity("alpha", "alpha", "alpha-up"),
                subscription_generation=1,
            )
        )
        await _wait_for(archive.started.is_set)
        acknowledged_while_blocked = write.done()
        archive.release.set()
        await write
        await writer.stop(clean=True)
        return acknowledged_while_blocked, archive.checkpoints

    acknowledged_while_blocked, checkpoints = asyncio.run(run())

    assert acknowledged_while_blocked is False
    assert len(checkpoints) == 1


@pytest.mark.parametrize("operation", ("open_gap", "close_gap", "anomaly"))
def test_gap_and_anomaly_mutations_do_not_acknowledge_before_commit_returns(
    operation: str,
) -> None:
    async def run() -> bool:
        archive = BlockingMutationArchive(operation)
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        market = _recording_market("alpha")
        identity = MarketIdentity(
            market.market.condition_id,
            market.market.slug,
        )
        if operation == "open_gap":
            mutation = asyncio.create_task(
                writer.open_gap(
                    CoverageGapPayload("disconnect", 10, None),
                    observed_at_ms=10,
                    identity=identity,
                    subscription_generation=1,
                )
            )
        elif operation == "close_gap":
            mutation = asyncio.create_task(writer.close_gap(1, ended_at_ms=10))
        else:
            mutation = asyncio.create_task(
                writer.record_anomaly(
                    _capture_anomaly_payload(_capture_continuity_error(market)),
                    observed_at_ms=10,
                    identity=identity,
                    subscription_generation=1,
                )
            )
        await _wait_for(archive.started.is_set)
        acknowledged_while_blocked = mutation.done()
        archive.release.set()
        await mutation
        await writer.stop(clean=True)
        return acknowledged_while_blocked

    assert asyncio.run(run()) is False


def test_concurrently_queued_records_share_one_group_commit() -> None:
    async def run() -> MemoryArchive:
        archive = MemoryArchive()
        writer = AsyncRecordingWriter(archive, batch_size=16)  # type: ignore[arg-type]
        writes = tuple(
            asyncio.create_task(
                writer.record(
                    _baseline_payload(token_id),
                    observed_at_ms=timestamp,
                    source_timestamp_ms=timestamp - 1,
                    identity=MarketIdentity(
                        token_id.split("-", 1)[0],
                        token_id.split("-", 1)[0],
                        token_id,
                    ),
                    subscription_generation=1,
                )
            )
            for token_id, timestamp in (
                ("alpha-up", 10),
                ("beta-down", 11),
                ("gamma-up", 12),
            )
        )
        await asyncio.gather(*writes)
        await writer.stop(clean=True)
        return archive

    archive = asyncio.run(run())

    assert [[event.sequence for event in batch] for batch in archive.event_batches] == [
        [1, 2, 3]
    ]


def test_writer_commits_event_and_checkpoint_batches_atomically() -> None:
    async def run() -> MemoryArchive:
        archive = MemoryArchive()
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        identities = (
            MarketIdentity("alpha", "alpha", "alpha-up"),
            MarketIdentity("alpha", "alpha", "alpha-down"),
        )
        await writer.record_batch(
            tuple(
                RecordingEventWrite(
                    payload=_baseline_payload(identity.token_id or ""),
                    observed_at_ms=10,
                    source_timestamp_ms=9,
                    identity=identity,
                    subscription_generation=1,
                )
                for identity in identities
            )
        )
        await writer.checkpoint_batch(
            tuple(
                RecordingCheckpointWrite(
                    book=_baseline_payload(identity.token_id or ""),
                    observed_at_ms=11,
                    identity=identity,
                    subscription_generation=1,
                )
                for identity in identities
            )
        )
        await writer.stop(clean=True)
        return archive

    archive = asyncio.run(run())

    assert [[event.sequence for event in batch] for batch in archive.event_batches] == [
        [1, 2]
    ]
    assert len(archive.checkpoint_batches) == 1
    assert [checkpoint.identity.token_id for checkpoint in archive.checkpoint_batches[0]] == [
        "alpha-up",
        "alpha-down",
    ]


def test_writer_queue_overflow_is_fatal_to_the_caller_not_lossy() -> None:
    async def run() -> tuple[list[int], list[tuple[bool, str | None]]]:
        archive = BlockingArchive()
        writer = AsyncRecordingWriter(
            archive,  # type: ignore[arg-type]
            queue_size=1,
            batch_size=1,
        )
        first = asyncio.create_task(
            writer.record(
                _baseline_payload("alpha-up"),
                observed_at_ms=10,
                source_timestamp_ms=9,
                identity=MarketIdentity("alpha", "alpha", "alpha-up"),
                subscription_generation=1,
            )
        )
        await _wait_for(archive.started.is_set)
        second = asyncio.create_task(
            writer.record(
                _baseline_payload("alpha-down"),
                observed_at_ms=11,
                source_timestamp_ms=10,
                identity=MarketIdentity("alpha", "alpha", "alpha-down"),
                subscription_generation=1,
            )
        )
        await asyncio.sleep(0)
        with pytest.raises(RecordingWriteQueueFullError):
            await writer.record(
                _baseline_payload("beta-up"),
                observed_at_ms=12,
                source_timestamp_ms=11,
                identity=MarketIdentity("beta", "beta", "beta-up"),
                subscription_generation=2,
            )
        archive.release.set()
        await asyncio.gather(first, second)
        await writer.flush()
        await writer.stop(clean=True)
        return [event.sequence for event in archive.events], archive.close_calls

    sequences, close_calls = asyncio.run(run())

    assert sequences == [1, 2]
    assert close_calls == [(True, None)]


def test_writer_surfaces_archive_failure_and_marks_unclean_close() -> None:
    async def run() -> tuple[BaseException | None, list[tuple[bool, str | None]]]:
        archive = FailingArchive()
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        with pytest.raises(OSError, match="disk failed"):
            await writer.record(
                _baseline_payload("alpha-up"),
                observed_at_ms=10,
                source_timestamp_ms=9,
                identity=MarketIdentity("alpha", "alpha", "alpha-up"),
                subscription_generation=1,
            )
        await _wait_for(lambda: writer.failure is not None)
        with pytest.raises(RecordingWriteError, match="recording writer failed"):
            await writer.stop(clean=False, failure_reason="disk failed")
        return writer.failure, archive.close_calls

    failure, close_calls = asyncio.run(run())

    assert isinstance(failure, OSError)
    assert len(close_calls) == 1
    assert close_calls[0][0] is False
    assert "disk failed" in (close_calls[0][1] or "")


def test_writer_failure_is_returned_by_the_acknowledged_record() -> None:
    async def run() -> BaseException | None:
        archive = FailingArchive()
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        with pytest.raises(OSError, match="disk failed"):
            await writer.record(
                _baseline_payload("alpha-up"),
                observed_at_ms=10,
                source_timestamp_ms=9,
                identity=MarketIdentity("alpha", "alpha", "alpha-up"),
                subscription_generation=1,
            )
        await _wait_for(lambda: writer.failure is not None)
        return writer.failure

    assert isinstance(asyncio.run(run()), OSError)


def test_cancelled_durable_write_does_not_fail_the_writer() -> None:
    async def run() -> tuple[BaseException | None, list[RecordedEvent]]:
        archive = BlockingArchive()
        writer = AsyncRecordingWriter(archive)  # type: ignore[arg-type]
        write = asyncio.create_task(
            writer.record(
                _baseline_payload("alpha-up"),
                observed_at_ms=10,
                source_timestamp_ms=9,
                    identity=MarketIdentity("alpha", "alpha", "alpha-up"),
                    subscription_generation=1,
                )
        )
        await _wait_for(archive.started.is_set)
        write.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write
        archive.release.set()
        await writer.flush()
        await writer.stop(clean=True)
        return writer.failure, archive.events

    failure, events = asyncio.run(run())

    assert failure is None
    assert [event.sequence for event in events] == [1]


def test_writer_failure_wakes_shutdown_waiting_on_a_full_queue() -> None:
    async def run() -> BaseException | None:
        archive = BlockingFailingArchive()
        writer = AsyncRecordingWriter(
            archive,  # type: ignore[arg-type]
            queue_size=1,
            batch_size=1,
        )
        first = asyncio.create_task(
            writer.record(
                _baseline_payload("alpha-up"),
                observed_at_ms=10,
                source_timestamp_ms=9,
                identity=MarketIdentity("alpha", "alpha", "alpha-up"),
                subscription_generation=1,
            )
        )
        await _wait_for(archive.started.is_set)
        second = asyncio.create_task(
            writer.record(
                _baseline_payload("alpha-down"),
                observed_at_ms=11,
                source_timestamp_ms=10,
                identity=MarketIdentity("alpha", "alpha", "alpha-down"),
                subscription_generation=1,
            )
        )
        await asyncio.sleep(0)
        stop = asyncio.create_task(
            writer.stop(clean=False, failure_reason="disk failed")
        )
        await asyncio.sleep(0)
        archive.release.set()
        with pytest.raises(OSError, match="disk failed"):
            await first
        with pytest.raises(OSError, match="disk failed"):
            await second
        with pytest.raises(OSError, match="disk failed"):
            await asyncio.wait_for(stop, timeout=1)
        return writer.failure

    assert isinstance(asyncio.run(run()), OSError)


def test_coordinator_records_all_interleaved_events_in_one_global_order() -> None:
    alpha = _recording_market("alpha")
    beta = _recording_market("beta")

    async def run() -> list[RecordedEvent]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha", "beta")))
        resolver = MutableResolver({"alpha": alpha, "beta": beta})
        coordinator = _coordinator(provider, resolver, feed, writer)
        await coordinator.start(provider.current_plan, (alpha, beta))
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))
        captures = {
            capture.market.condition_id: capture for capture in feed.captures
        }

        emitted = (
            (captures[alpha.market.condition_id], _baseline_event(alpha, 0, 10)),
            (captures[beta.market.condition_id], _baseline_event(beta, 0, 11)),
            (captures[alpha.market.condition_id], _baseline_event(alpha, 1, 12)),
            (captures[beta.market.condition_id], _baseline_event(beta, 1, 13)),
            (captures[alpha.market.condition_id], _delta_event(alpha, "0.44", 14)),
            (captures[alpha.market.condition_id], _delta_event(alpha, "0.45", 15)),
        )
        recorded_count = len(writer.events)
        for capture, event in emitted:
            await capture.emit(event)
            recorded_count += 1
            await _wait_for(lambda: len(writer.events) >= recorded_count)

        shutdown.set()
        await task
        return writer.events

    events = asyncio.run(run())
    market_events = [
        event
        for event in events
        if isinstance(event.payload, (BookBaselinePayload, BookDeltaPayload))
    ]

    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [
        (
            type(event.payload).__name__,
            event.identity.condition_id if event.identity else None,
        )
        for event in market_events
    ] == [
        ("BookBaselinePayload", "condition-alpha"),
        ("BookBaselinePayload", "condition-beta"),
        ("BookBaselinePayload", "condition-alpha"),
        ("BookBaselinePayload", "condition-beta"),
        ("BookDeltaPayload", "condition-alpha"),
        ("BookDeltaPayload", "condition-alpha"),
    ]
    assert [
        event.payload.changes[0].price
        for event in market_events
        if isinstance(event.payload, BookDeltaPayload)
    ] == [Decimal("0.44"), Decimal("0.45")]


def test_coordinator_retries_next_market_deduplicates_and_retains_prior_market() -> None:
    alpha = _recording_market("alpha")
    beta = _recording_market("beta")

    async def run() -> tuple[
        RecordingCoordinator,
        FakeFeed,
        MutableResolver,
        list[str],
    ]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        initial = _plan(("alpha",), ("beta",))
        provider = MutablePlanProvider(initial)
        resolver = MutableResolver({"alpha": alpha, "beta": None})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            plan_refresh_seconds=0.01,
        )
        await coordinator.start(initial, (alpha,))
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))
        await _wait_for(
            lambda: sum("beta" in call for call in resolver.calls) >= 2
        )

        resolver.markets["beta"] = beta
        await _wait_for(lambda: beta.market.condition_id in coordinator.tracked_condition_ids)
        await _wait_for(lambda: len(feed.captures) == 2)

        provider.current_plan = _plan(("beta",), ("beta-alias",))
        resolver.markets["beta-alias"] = beta
        await _wait_for(
            lambda: any("beta-alias" in call for call in resolver.calls)
        )
        await _wait_for(lambda: "beta-alias" not in coordinator.pending_slugs)

        assert coordinator.tracked_condition_ids == {
            alpha.market.condition_id,
            beta.market.condition_id,
        }
        assert len(feed.captures) == 2
        alpha_capture = feed.latest(alpha.market.condition_id)
        assert alpha_capture.closed is False

        await alpha_capture.emit(_resolution_event(alpha, 20))
        await _wait_for(lambda: alpha_capture.closed)
        shutdown.set()
        await task
        return coordinator, feed, resolver, operations

    coordinator, feed, resolver, operations = asyncio.run(run())

    assert coordinator.tracked_condition_ids == {
        "condition-alpha",
        "condition-beta",
    }
    assert sum("beta" in call for call in resolver.calls) >= 2
    assert len(feed.captures) == 2
    resolution_index = operations.index("record:ResolutionPayload")
    close_index = next(
        index
        for index, operation in enumerate(operations)
        if operation.startswith("close:condition-alpha")
    )
    assert resolution_index < close_index


def test_coordinator_requires_both_baselines_before_gap_close_and_checkpoints() -> None:
    market = _recording_market("alpha")

    async def run() -> tuple[MemoryWriter, FakeCapture]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            checkpoint_seconds=0.01,
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await asyncio.sleep(0.025)
        assert writer.checkpoints == []
        await capture.emit(_baseline_event(market, 0, 10))
        await _wait_for(
            lambda: any(
                isinstance(event.payload, BookBaselinePayload)
                for event in writer.events
            )
        )
        await asyncio.sleep(0.025)
        assert writer.closed_gaps == []
        assert writer.checkpoints == []

        await capture.emit(_baseline_event(market, 1, 11))
        await _wait_for(lambda: len(writer.checkpoints) >= 2)
        checkpoint_count = len(writer.checkpoints)
        await capture.emit(_delta_event(market, "0.45", 12))
        await _wait_for(
            lambda: any(
                isinstance(event.payload, BookDeltaPayload)
                for event in writer.events
            )
        )
        await _wait_for(lambda: len(writer.checkpoints) >= checkpoint_count + 2)
        shutdown.set()
        await task
        return writer, capture

    writer, capture = asyncio.run(run())

    assert capture.ready is True
    assert {checkpoint.book.token_id for checkpoint in writer.checkpoints} == set(
        market.market.token_ids
    )
    assert any(
        level.price == Decimal("0.45")
        for checkpoint in writer.checkpoints
        if checkpoint.book.token_id == market.market.token_ids[0]
        for level in checkpoint.book.bids
    )
    assert writer.closed_gaps == []


def test_checkpoint_excludes_feed_projected_state_not_recorded_by_coordinator() -> None:
    market = _recording_market("alpha")

    async def run() -> tuple[BookCheckpoint, ...]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            checkpoint_seconds=0.01,
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await capture.emit(_baseline_event(market, 0, 10))
        await capture.emit(_baseline_event(market, 1, 11))
        await _wait_for(lambda: len(writer.checkpoints) >= 2)
        writer.checkpoints.clear()

        capture.project_unrecorded_bid(
            market.market.token_ids[0],
            Decimal("0.99"),
        )
        await _wait_for(lambda: len(writer.checkpoints) >= 2)
        checkpoints = tuple(writer.checkpoints)
        shutdown.set()
        await task
        return checkpoints

    checkpoints = asyncio.run(run())
    up_checkpoint = next(
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.book.token_id == market.market.token_ids[0]
    )

    assert tuple(level.price for level in up_checkpoint.book.bids) == (
        Decimal("0.40"),
    )


def test_sdk_drop_reopens_only_affected_condition_until_fresh_baselines() -> None:
    market = _recording_market("alpha")

    async def run() -> tuple[MemoryWriter, FakeFeed]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            plan_refresh_seconds=0.01,
        )
        await coordinator.start(provider.current_plan, (market,))
        first = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await first.emit(_baseline_event(market, 0, 10))
        await first.emit(_baseline_event(market, 1, 11))
        await _wait_for(lambda: first.ready)

        first.dropped_count = 1
        await _wait_for(lambda: len(feed.captures) == 2)
        second = feed.latest(market.market.condition_id)
        assert first.closed is True
        assert second.generation != first.generation
        assert len(writer.closed_gaps) == 0

        await second.emit(_baseline_event(market, 0, 20))
        await asyncio.sleep(0.02)
        assert len(writer.closed_gaps) == 0
        await second.emit(_baseline_event(market, 1, 21))
        await _wait_for(lambda: len(writer.closed_gaps) == 1)
        shutdown.set()
        await task
        return writer, feed

    writer, feed = asyncio.run(run())

    gap_reasons = [
        event.payload.reason
        for event in writer.events
        if isinstance(event.payload, CoverageGapPayload)
    ]
    assert gap_reasons == ["sdk_handle_drop"]
    assert len(feed.captures) == 2


def test_capture_pump_uses_bounded_commit_pipeline_during_event_burst() -> None:
    market = _recording_market("alpha")
    pending_limit = 16

    class DeferredWriter(MemoryWriter):
        def __init__(self, operations: list[str]) -> None:
            super().__init__(operations)
            self.defer = False
            self.completions: list[asyncio.Future[None]] = []
            self.high_watermark = 0

        def enqueue_record(
            self,
            payload: object,
            *,
            observed_at_ms: int,
            source_timestamp_ms: int | None,
            identity: MarketIdentity | None,
            subscription_generation: int,
        ) -> PendingRecordingEvent:
            event = self._record_now(
                payload,
                observed_at_ms=observed_at_ms,
                source_timestamp_ms=source_timestamp_ms,
                identity=identity,
                subscription_generation=subscription_generation,
            )
            completion = asyncio.get_running_loop().create_future()
            if self.defer:
                self.completions.append(completion)
                self.high_watermark = max(
                    self.high_watermark,
                    len(self.completions),
                )
            else:
                completion.set_result(None)
            return PendingRecordingEvent(event, completion)

        def release_pending(self) -> None:
            completions = tuple(self.completions)
            self.completions.clear()
            for completion in completions:
                completion.set_result(None)

    async def run() -> tuple[DeferredWriter, FakeCapture]:
        operations: list[str] = []
        writer = DeferredWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            max_pending_capture_events=pending_limit,
            checkpoint_seconds=60.0,
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        writer.defer = True
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        captured = (
            _baseline_event(market, 0, 10),
            _baseline_event(market, 1, 11),
            *(
                _delta_event(market, "0.41", source_timestamp_ms)
                for source_timestamp_ms in range(12, 44)
            ),
        )
        for event in captured:
            await capture.emit(event)

        await _wait_for(lambda: len(writer.completions) == pending_limit)
        expected_event_count = 1 + len(captured)
        while len(writer.events) < expected_event_count:
            previous_count = len(writer.events)
            writer.release_pending()
            await _wait_for(lambda: len(writer.events) > previous_count)
        writer.release_pending()
        await _wait_for(
            lambda: coordinator._tracked[market.market.condition_id].last_observed_at_ms
            == writer.events[-1].observed_at_ms
        )
        shutdown.set()
        await task
        return writer, capture

    writer, capture = asyncio.run(run())

    assert writer.high_watermark == pending_limit
    assert capture.dropped_count == 0
    assert not any(
        isinstance(event.payload, CoverageGapPayload) for event in writer.events
    )


def test_sdk_drop_gap_starts_at_last_known_good_event() -> None:
    market = _recording_market("alpha")

    async def run() -> tuple[MemoryWriter, int, int]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            plan_refresh_seconds=60.0,
            checkpoint_seconds=60.0,
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await capture.emit(_baseline_event(market, 0, 10))
        await capture.emit(_baseline_event(market, 1, 11))
        await _wait_for(
            lambda: sum(
                isinstance(event.payload, BookBaselinePayload)
                for event in writer.events
            )
            == 2
        )
        last_good_observed_at_ms = writer.events[-1].observed_at_ms

        capture.dropped_count = 1
        await capture.emit(_delta_event(market, "0.45", 12))
        await _wait_for(
            lambda: any(
                isinstance(event.payload, CoverageGapPayload)
                and event.payload.reason == "sdk_handle_drop"
                for event in writer.events
            )
        )
        gap = next(
            event.payload
            for event in writer.events
            if isinstance(event.payload, CoverageGapPayload)
            and event.payload.reason == "sdk_handle_drop"
        )
        delta_count = sum(
            isinstance(event.payload, BookDeltaPayload) for event in writer.events
        )
        shutdown.set()
        await task
        return writer, last_good_observed_at_ms, delta_count

    writer, last_good_observed_at_ms, delta_count = asyncio.run(run())
    gap = next(
        event.payload
        for event in writer.events
        if isinstance(event.payload, CoverageGapPayload)
        and event.payload.reason == "sdk_handle_drop"
    )

    assert gap.started_at_ms == last_good_observed_at_ms
    assert delta_count == 0


def test_capture_failure_reopens_condition_and_closes_gap_after_rebaseline() -> None:
    market = _recording_market("alpha")

    async def run() -> tuple[MemoryWriter, FakeFeed]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            checkpoint_seconds=60.0,
        )
        await coordinator.start(provider.current_plan, (market,))
        first = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await first.emit(_baseline_event(market, 0, 10))
        await first.emit(_baseline_event(market, 1, 11))
        await _wait_for(
            lambda: sum(
                isinstance(event.payload, BookBaselinePayload)
                for event in writer.events
            )
            == 2
        )
        await first.fail(RuntimeError("subscription disconnected"))
        await _wait_for(lambda: len(feed.captures) == 2)
        second = feed.latest(market.market.condition_id)
        gap = next(
            event.payload
            for event in writer.events
            if isinstance(event.payload, CoverageGapPayload)
            and event.payload.reason == "capture_failure"
        )
        assert gap.details == "RuntimeError: subscription disconnected"
        assert first.closed is True

        await second.emit(_baseline_event(market, 0, 20))
        await asyncio.sleep(0.01)
        assert writer.closed_gaps == []
        assert writer.checkpoints == []
        await second.emit(_baseline_event(market, 1, 21))
        await _wait_for(
            lambda: len(writer.closed_gaps) == 1
            and len(writer.checkpoints) == 2
        )
        shutdown.set()
        await task
        return writer, feed

    writer, feed = asyncio.run(run())

    assert len(feed.captures) == 2
    assert writer.closed_gaps[0][0] == 1
    assert {checkpoint.book.token_id for checkpoint in writer.checkpoints} == set(
        market.market.token_ids
    )
    assert {checkpoint.sequence for checkpoint in writer.checkpoints} == {
        writer.events[-1].sequence
    }
    checkpoint_times = {
        checkpoint.observed_at_ms for checkpoint in writer.checkpoints
    }
    assert len(checkpoint_times) == 1
    assert min(checkpoint_times) >= writer.closed_gaps[0][1]


def test_split_revision_failures_are_quarantined_and_each_journaled() -> None:
    market = _recording_market("alpha")

    async def run() -> tuple[MemoryWriter, int]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(provider, resolver, feed, writer)
        await coordinator.start(provider.current_plan, (market,))
        first = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await first.emit(_baseline_event(market, 0, 10))
        await first.emit(_baseline_event(market, 1, 11))
        await _wait_for(
            lambda: sum(
                isinstance(event.payload, BookBaselinePayload)
                for event in writer.events
            )
            == 2
        )
        events_before_failures = len(writer.events)

        await first.fail(_capture_continuity_error(market))
        await _wait_for(lambda: len(feed.captures) == 2 and len(writer.anomalies) == 1)
        second = feed.latest(market.market.condition_id)
        await second.fail(_capture_continuity_error(market))
        await _wait_for(lambda: len(feed.captures) == 3 and len(writer.anomalies) == 2)

        shutdown.set()
        await task
        return writer, events_before_failures

    writer, events_before_failures = asyncio.run(run())

    gaps = [
        event
        for event in writer.events
        if isinstance(event.payload, CoverageGapPayload)
    ]
    assert len(gaps) == 1
    assert len(writer.events) == events_before_failures + 1
    assert not any(
        isinstance(event.payload, BookDeltaPayload) for event in writer.events
    )
    assert len(writer.anomalies) == 2
    anomaly = writer.anomalies[0].anomaly
    assert anomaly.failure_kind is CaptureFailureKind.SPLIT_REVISION_MISMATCH
    assert tuple(fragment.role for fragment in anomaly.fragments) == (
        CaptureFragmentRole.INITIAL,
        CaptureFragmentRole.MISMATCHING_CONTINUATION,
    )
    assert anomaly.elapsed_ms == 12
    up_diagnostics = next(
        diagnostics
        for diagnostics in anomaly.book_diagnostics
        if diagnostics.token_id == market.market.token_ids[0]
    )
    assert up_diagnostics.projected_best_bid == Decimal("0.40")
    assert up_diagnostics.projected_best_ask == Decimal("0.60")
    assert up_diagnostics.advertised_best_bid == Decimal("0.62")
    assert up_diagnostics.advertised_best_ask == Decimal("0.60")


def test_resumed_open_gap_checkpoints_all_markets_at_final_rebaseline() -> None:
    alpha = _recording_market("alpha")
    beta = _recording_market("beta")

    async def run() -> MemoryWriter:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha", "beta")))
        resolver = MutableResolver({"alpha": alpha, "beta": beta})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            resumed_gap_condition_ids={
                41: frozenset(
                    (alpha.market.condition_id, beta.market.condition_id)
                )
            },
            checkpoint_seconds=60.0,
        )
        await coordinator.start(provider.current_plan, (alpha, beta))
        captures = {
            capture.market.condition_id: capture for capture in feed.captures
        }
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await captures[alpha.market.condition_id].emit(
            _baseline_event(alpha, 0, 10)
        )
        await captures[alpha.market.condition_id].emit(
            _baseline_event(alpha, 1, 11)
        )
        await asyncio.sleep(0.01)
        assert writer.closed_gaps == []
        assert writer.checkpoints == []

        await captures[beta.market.condition_id].emit(
            _baseline_event(beta, 0, 12)
        )
        await asyncio.sleep(0.01)
        assert writer.checkpoints == []
        await captures[beta.market.condition_id].emit(
            _baseline_event(beta, 1, 13)
        )
        await _wait_for(
            lambda: len(writer.closed_gaps) == 1
            and len(writer.checkpoints) == 4
        )
        shutdown.set()
        await task
        return writer

    writer = asyncio.run(run())
    gap_id, ended_at_ms = writer.closed_gaps[0]

    assert gap_id == 41
    assert {checkpoint.book.token_id for checkpoint in writer.checkpoints} == {
        *alpha.market.token_ids,
        *beta.market.token_ids,
    }
    assert {checkpoint.sequence for checkpoint in writer.checkpoints} == {
        writer.events[-1].sequence
    }
    checkpoint_times = {
        checkpoint.observed_at_ms for checkpoint in writer.checkpoints
    }
    assert len(checkpoint_times) == 1
    assert min(checkpoint_times) >= ended_at_ms


def test_recovery_checkpoint_batch_stays_monotonic_after_reverse_ack_order() -> None:
    alpha = _recording_market("alpha")
    beta = _recording_market("beta")

    class ReverseAckWriter(MemoryWriter):
        def __init__(self, operations: list[str]) -> None:
            super().__init__(operations)
            self.alpha_final_started = asyncio.Event()
            self.release_alpha = asyncio.Event()
            self.checkpoint_batches: list[tuple[BookCheckpoint, ...]] = []

        def enqueue_record(
            self,
            payload: object,
            *,
            observed_at_ms: int,
            source_timestamp_ms: int | None,
            identity: MarketIdentity | None,
            subscription_generation: int,
        ) -> PendingRecordingEvent:
            event = self._record_now(
                payload,
                observed_at_ms=observed_at_ms,
                source_timestamp_ms=source_timestamp_ms,
                identity=identity,
                subscription_generation=subscription_generation,
            )
            completion = asyncio.get_running_loop().create_future()
            if (
                isinstance(payload, BookBaselinePayload)
                and payload.token_id == alpha.market.token_ids[1]
            ):
                async def complete_after_release() -> None:
                    self.alpha_final_started.set()
                    await self.release_alpha.wait()
                    completion.set_result(None)

                asyncio.create_task(complete_after_release())
            else:
                completion.set_result(None)
            return PendingRecordingEvent(event, completion)

        async def checkpoint_batch(
            self,
            writes: tuple[RecordingCheckpointWrite, ...],
        ) -> tuple[BookCheckpoint, ...]:
            checkpoints = await super().checkpoint_batch(writes)
            self.checkpoint_batches.append(checkpoints)
            return checkpoints

    async def run() -> ReverseAckWriter:
        operations: list[str] = []
        writer = ReverseAckWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha", "beta")))
        resolver = MutableResolver({"alpha": alpha, "beta": beta})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            resumed_gap_condition_ids={
                41: frozenset(
                    (alpha.market.condition_id, beta.market.condition_id)
                )
            },
            checkpoint_seconds=60.0,
        )
        await coordinator.start(provider.current_plan, (alpha, beta))
        captures = {
            capture.market.condition_id: capture for capture in feed.captures
        }
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await captures[alpha.market.condition_id].emit(
            _baseline_event(alpha, 0, 10)
        )
        await captures[beta.market.condition_id].emit(
            _baseline_event(beta, 0, 11)
        )
        await captures[alpha.market.condition_id].emit(
            _baseline_event(alpha, 1, 12)
        )
        await writer.alpha_final_started.wait()
        await captures[beta.market.condition_id].emit(
            _baseline_event(beta, 1, 13)
        )
        await _wait_for(
            lambda: coordinator._resumed_gap_conditions[41]
            == {alpha.market.condition_id}
        )
        writer.release_alpha.set()
        await _wait_for(lambda: len(writer.checkpoints) == 4)
        shutdown.set()
        await task
        return writer

    writer = asyncio.run(run())

    assert len(writer.checkpoint_batches) == 1
    assert len(writer.checkpoint_batches[0]) == 4
    checkpoint_times = {
        checkpoint.observed_at_ms for checkpoint in writer.checkpoints
    }
    assert len(checkpoint_times) == 1
    assert min(checkpoint_times) >= max(
        event.observed_at_ms for event in writer.events
    )


def test_resolution_closes_resumed_gap_without_fabricating_checkpoint() -> None:
    market = _recording_market("alpha")

    async def run() -> MemoryWriter:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = _coordinator(
            provider,
            resolver,
            feed,
            writer,
            checkpoint_seconds=60.0,
            resumed_gap_condition_ids={
                41: frozenset((market.market.condition_id,))
            },
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        shutdown = asyncio.Event()
        task = asyncio.create_task(coordinator.run(shutdown))

        await capture.emit(_resolution_event(market, 20))
        await _wait_for(lambda: len(writer.closed_gaps) == 1)
        shutdown.set()
        await task
        return writer

    writer = asyncio.run(run())

    assert writer.closed_gaps[0][0] == 41
    assert writer.checkpoints == []


def test_resume_state_restores_a_prior_open_condition_gap(tmp_path) -> None:
    market = _recording_market("alpha")
    started_at_ms = time.time_ns() // 1_000_000
    path = tmp_path / "capture.sqlite3"
    archive = RecordingArchive.create(
        path,
        target_identity="static-alpha",
        started_at_ms=started_at_ms,
    )
    archive.append_metadata(
        RecordedEvent(
            sequence=archive.next_sequence,
            session_id=archive.session_id,
            subscription_generation=0,
            observed_at_ms=started_at_ms,
            source_timestamp_ms=None,
            identity=MarketIdentity(
                condition_id=market.market.condition_id,
                market_slug=market.market.slug,
            ),
            payload=market.metadata,
        )
    )
    gap_id = archive.append_gap(
        RecordedEvent(
            sequence=archive.next_sequence,
            session_id=archive.session_id,
            subscription_generation=1,
            observed_at_ms=started_at_ms + 1,
            source_timestamp_ms=None,
            identity=MarketIdentity(
                condition_id=market.market.condition_id,
                market_slug=market.market.slug,
            ),
            payload=CoverageGapPayload(
                reason="sdk_handle_drop",
                started_at_ms=started_at_ms + 1,
                ended_at_ms=None,
                affected_condition_ids=(market.market.condition_id,),
                affected_market_slugs=(market.market.slug,),
                affected_token_ids=market.market.token_ids,
            ),
        )
    )
    archive.append_event(
        RecordedEvent(
            sequence=archive.next_sequence,
            session_id=archive.session_id,
            subscription_generation=1,
            observed_at_ms=started_at_ms + 2,
            source_timestamp_ms=started_at_ms + 2,
            identity=MarketIdentity(
                condition_id=market.market.condition_id,
                market_slug=market.market.slug,
            ),
            payload=ResolutionPayload(
                token_ids=market.market.token_ids,
                winning_token_id=market.market.token_ids[0],
                winning_outcome="Up",
                source="market_websocket",
            ),
        )
    )
    archive.close()

    resume_state = _read_resume_state(path, "static-alpha")

    assert resume_state.restored_slugs == ("alpha",)
    assert resume_state.open_gap_condition_ids == (
        (gap_id, frozenset((market.market.condition_id,))),
    )


def test_static_coordinator_stops_after_resolution_is_durably_recorded() -> None:
    market = _recording_market("alpha")
    resolved_market = _recording_market("alpha", resolved=True)

    async def run() -> tuple[RecordingCoordinator, MemoryWriter, list[str]]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = RecordingCoordinator(
            provider=provider,
            resolver=resolver,  # type: ignore[arg-type]
            feed=feed,  # type: ignore[arg-type]
            writer=writer,  # type: ignore[arg-type]
            clock=StepClock(),  # type: ignore[arg-type]
            stop_when_terminal=True,
            plan_refresh_seconds=1.0,
            checkpoint_seconds=1.0,
            resolution_reconciliation_seconds=60.0,
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        task = asyncio.create_task(coordinator.run(asyncio.Event()))

        resolver.markets["alpha"] = resolved_market
        await capture.emit(_resolution_event(market, 20))
        await asyncio.wait_for(task, timeout=1)
        await coordinator.close()
        return coordinator, writer, operations

    coordinator, writer, operations = asyncio.run(run())

    assert coordinator.terminal is True
    assert operations.index("record:ResolutionPayload") < next(
        index
        for index, operation in enumerate(operations)
        if operation.startswith("close:condition-alpha")
    )
    assert isinstance(writer.events[-1].payload, MarketMetadataPayload)
    assert writer.events[-1].payload.resolved is True


def test_terminal_metadata_reconciliation_retries_until_gamma_is_final() -> None:
    market = _recording_market("alpha")
    resolved_market = _recording_market("alpha", resolved=True)

    async def run() -> tuple[RecordingCoordinator, MemoryWriter]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = RecordingCoordinator(
            provider=provider,
            resolver=resolver,  # type: ignore[arg-type]
            feed=feed,  # type: ignore[arg-type]
            writer=writer,  # type: ignore[arg-type]
            clock=StepClock(),  # type: ignore[arg-type]
            stop_when_terminal=True,
            plan_refresh_seconds=1.0,
            checkpoint_seconds=1.0,
            resolution_reconciliation_seconds=0.01,
        )
        await coordinator.start(provider.current_plan, (market,))
        capture = feed.latest(market.market.condition_id)
        task = asyncio.create_task(coordinator.run(asyncio.Event()))

        await capture.emit(_resolution_event(market, 20))
        await _wait_for(lambda: capture.closed)
        assert not task.done()
        resolver.markets["alpha"] = resolved_market
        await asyncio.wait_for(task, timeout=1)
        await coordinator.close()
        return coordinator, writer

    coordinator, writer = asyncio.run(run())

    assert coordinator.terminal is True
    assert isinstance(writer.events[-1].payload, MarketMetadataPayload)
    assert writer.events[-1].payload.resolved is True


def test_initially_resolved_restored_market_is_recorded_without_subscription() -> None:
    market = _recording_market("alpha", resolved=True)

    async def run() -> tuple[RecordingCoordinator, MemoryWriter, FakeFeed]:
        operations: list[str] = []
        writer = MemoryWriter(operations)
        feed = FakeFeed(operations)
        provider = MutablePlanProvider(_plan(("alpha",)))
        resolver = MutableResolver({"alpha": market})
        coordinator = RecordingCoordinator(
            provider=provider,
            resolver=resolver,  # type: ignore[arg-type]
            feed=feed,  # type: ignore[arg-type]
            writer=writer,  # type: ignore[arg-type]
            clock=StepClock(),  # type: ignore[arg-type]
            stop_when_terminal=True,
        )

        await coordinator.start(provider.current_plan, (market,))
        await coordinator.close()
        return coordinator, writer, feed

    coordinator, writer, feed = asyncio.run(run())

    assert coordinator.terminal is True
    assert feed.captures == []
    assert [type(event.payload) for event in writer.events] == [
        MarketMetadataPayload,
        ResolutionPayload,
    ]


def test_initial_resolution_requires_all_current_markets_but_not_future_market() -> None:
    current = _recording_market("current")
    resolver = MutableResolver({"current": current, "next": None})

    resolved, missing_restored = asyncio.run(
        _resolve_initial_markets(
            resolver,  # type: ignore[arg-type]
            _plan(("current",), ("next",)),
            (),
        )
    )

    assert resolved == (current,)
    assert missing_restored == ()

    with pytest.raises(RuntimeError, match="current markets could not be resolved"):
        asyncio.run(
            _resolve_initial_markets(
                MutableResolver({"missing": None}),  # type: ignore[arg-type]
                _plan(("missing",)),
                (),
            )
        )


def test_service_refuses_overwrite_and_resume_appends_offline_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polybot.recording import service

    market = _recording_market("alpha")
    resolvers: list[MutableResolver] = []
    feeds: list[FakeFeed] = []

    class IncreasingClock:
        next_anchor = time.time_ns() // 1_000_000 + 10_000

        def __init__(self) -> None:
            self._now = type(self).next_anchor
            type(self).next_anchor += 10_000

        def now_ms(self) -> int:
            self._now += 1
            return self._now

        def advance_to(self, observed_at_ms: int) -> None:
            self._now = max(self._now, observed_at_ms)

    class ImmediateCoordinator:
        def __init__(self, **kwargs: object) -> None:
            self.closed = False

        async def start(self, *args: object, **kwargs: object) -> None:
            return None

        async def run(self, shutdown: asyncio.Event) -> None:
            return None

        async def close(self) -> None:
            self.closed = True

    def resolver_factory(client: object) -> MutableResolver:
        resolver = MutableResolver({"alpha": market})
        resolvers.append(resolver)
        return resolver

    def feed_factory(client: object) -> FakeFeed:
        feed = FakeFeed([])
        feeds.append(feed)
        return feed

    monkeypatch.setattr(service, "ObservationClock", IncreasingClock)
    monkeypatch.setattr(service, "RecordingMarketResolver", resolver_factory)
    monkeypatch.setattr(service, "MarketRecordingFeed", feed_factory)
    monkeypatch.setattr(service, "GammaClient", lambda client: object())
    monkeypatch.setattr(service, "ClobClient", lambda client: object())
    monkeypatch.setattr(service, "RecordingCoordinator", ImmediateCoordinator)

    output = tmp_path / "capture.sqlite3"
    kwargs = {
        "output_path": output,
        "target_identity": "static-alpha",
        "market_slugs": ("alpha",),
        "client": object(),
    }
    asyncio.run(record_markets(BotConfig(name="recorder"), **kwargs))

    with pytest.raises(ArchiveExistsError):
        asyncio.run(record_markets(BotConfig(name="recorder"), **kwargs))

    asyncio.run(
        record_markets(
            BotConfig(name="recorder"),
            **kwargs,
            resume=True,
        )
    )

    with RecordingReader(output) as reader:
        sessions = reader.sessions()
        gaps = reader.coverage_gaps()

    assert len(sessions) == 2
    assert [gap.gap.reason for gap in gaps] == ["recorder_offline"]
    assert gaps[0].gap.ended_at_ms is not None
    assert all(resolver.closed for resolver in resolvers)
    assert all(feed.closed for feed in feeds)


def test_cancelled_recording_is_finalized_at_its_durable_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polybot.recording import service

    market = _recording_market("alpha")
    coordinators: list[CancellingCoordinator] = []

    class CancellingCoordinator:
        def __init__(self, **kwargs: object) -> None:
            self.writer = kwargs["writer"]
            self.clock = kwargs["clock"]
            self.boundary_ms: int | None = None
            self.closed = False
            coordinators.append(self)

        async def start(
            self,
            plan: StreamPlan,
            markets: tuple[RecordingMarket, ...],
            **kwargs: object,
        ) -> None:
            recording = markets[0]
            self.boundary_ms = self.clock.now_ms()
            await self.writer.record(
                recording.metadata,
                observed_at_ms=self.boundary_ms,
                source_timestamp_ms=None,
                identity=MarketIdentity(
                    recording.market.condition_id,
                    recording.market.slug,
                ),
                subscription_generation=0,
            )

        async def run(self, shutdown: asyncio.Event) -> None:
            raise asyncio.CancelledError

        async def close(self) -> None:
            self.closed = True

    resolver = MutableResolver({"alpha": market})
    feed = FakeFeed([])
    monkeypatch.setattr(service, "RecordingMarketResolver", lambda client: resolver)
    monkeypatch.setattr(service, "MarketRecordingFeed", lambda client: feed)
    monkeypatch.setattr(service, "GammaClient", lambda client: object())
    monkeypatch.setattr(service, "ClobClient", lambda client: object())
    monkeypatch.setattr(service, "RecordingCoordinator", CancellingCoordinator)

    output = tmp_path / "cancelled.sqlite3"
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            record_markets(
                BotConfig(name="recorder"),
                output_path=output,
                target_identity="static-alpha",
                market_slugs=("alpha",),
                client=object(),
            )
        )

    with RecordingReader(output) as reader:
        (session,) = reader.sessions()
    (coordinator,) = coordinators
    assert session.ended_at_ms == coordinator.boundary_ms
    assert session.clean_close is False
    assert session.integrity_status is SessionIntegrityStatus.FAILED
    assert session.failure_reason == CANCELLED_RECORDING_REASON
    assert coordinator.closed is True
    assert resolver.closed is True
    assert feed.closed is True


def test_finalization_still_marks_writer_failed_when_coordinator_cleanup_fails() -> None:
    class FailingCoordinator:
        async def close(self) -> None:
            raise RuntimeError("capture cleanup failed")

    class FinalizingWriter:
        def __init__(self) -> None:
            self.calls: list[tuple[bool, str | None]] = []

        async def stop(
            self,
            *,
            clean: bool,
            failure_reason: str | None = None,
        ) -> None:
            self.calls.append((clean, failure_reason))

    async def run() -> FinalizingWriter:
        writer = FinalizingWriter()
        with pytest.raises(RuntimeError, match="capture cleanup failed"):
            await _finish_recording(
                FailingCoordinator(),  # type: ignore[arg-type]
                writer,  # type: ignore[arg-type]
                clean=True,
            )
        return writer

    writer = asyncio.run(run())

    assert writer.calls == [(False, "RuntimeError: capture cleanup failed")]


def test_recording_cli_parses_static_targets_duration_and_resume() -> None:
    parser = entrypoint._argument_parser()
    args = parser.parse_args(
        (
            "--market-slug",
            "alpha",
            "--market-slug",
            "beta",
            "--output",
            "capture.sqlite3",
            "--duration",
            "2h",
            "--resume",
        )
    )

    assert args.market_slug == ["alpha", "beta"]
    assert args.duration == 7_200
    assert args.resume is True

    with pytest.raises(SystemExit):
        parser.parse_args(())
    with pytest.raises(SystemExit):
        parser.parse_args(
            (
                "--bot",
                "example:create",
                "--market-slug",
                "alpha",
                "--output",
                "capture.sqlite3",
            )
        )


def test_default_recording_output_path_uses_timestamped_directory() -> None:
    path = entrypoint.default_output_path(
        bot_spec=None,
        market_slugs=("alpha", "beta"),
        now=datetime(2026, 7, 19, 12, 34, 56),
        recordings_dir=Path("recordings"),
    )

    assert path == Path("recordings/20260719-123456/markets.sqlite3")

    bot_path = entrypoint.default_output_path(
        bot_spec="polybot.examples.my_bot:create",
        market_slugs=(),
        now=datetime(2026, 7, 19, 12, 34, 56),
    )
    assert bot_path == Path(
        "recordings/20260719-123456/bot-my_bot.sqlite3"
    )


def test_recording_cli_forwards_normalized_static_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_record_markets(config: BotConfig, **kwargs: object) -> None:
        captured["config"] = config
        captured.update(kwargs)

    monkeypatch.setattr(entrypoint, "load_dotenv", lambda path: None)
    monkeypatch.setattr(entrypoint, "parse_overrides", lambda values: {})
    monkeypatch.setattr(
        entrypoint.BotConfig,
        "from_env",
        classmethod(lambda cls, name: BotConfig(name=name)),
    )
    monkeypatch.setattr(entrypoint, "record_markets", fake_record_markets)

    result = entrypoint.main(
        [
            "--market-slug",
            " alpha ",
            "--market-slug",
            "alpha",
            "--market-slug",
            "beta",
            "--output",
            "capture.sqlite3",
            "--duration",
            "2m",
            "--resume",
        ]
    )

    assert result == 0
    assert captured["market_slugs"] == ("alpha", "beta")
    assert captured["duration_seconds"] == 120
    assert captured["resume"] is True
    assert captured["output_path"] == Path("capture.sqlite3")
    config = captured["config"]
    assert isinstance(config, BotConfig)
    assert config.live_enabled is False


def _coordinator(
    provider: MutablePlanProvider,
    resolver: MutableResolver,
    feed: FakeFeed,
    writer: MemoryWriter,
    *,
    plan_refresh_seconds: float = 1.0,
    checkpoint_seconds: float = 1.0,
    max_pending_capture_events: int = 64,
    resumed_gap_condition_ids: dict[int, frozenset[str]] | None = None,
) -> RecordingCoordinator:
    return RecordingCoordinator(
        provider=provider,
        resolver=resolver,  # type: ignore[arg-type]
        feed=feed,  # type: ignore[arg-type]
        writer=writer,  # type: ignore[arg-type]
        clock=StepClock(),  # type: ignore[arg-type]
        stop_when_terminal=False,
        plan_refresh_seconds=plan_refresh_seconds,
        checkpoint_seconds=checkpoint_seconds,
        resolution_reconciliation_seconds=60.0,
        max_pending_capture_events=max_pending_capture_events,
        resumed_gap_condition_ids=resumed_gap_condition_ids,
    )


def _plan(
    current: tuple[str, ...],
    next_markets: tuple[str, ...] = (),
) -> StreamPlan:
    return StreamPlan(
        current=(
            StreamRule(
                StreamRelation.INDEPENDENT,
                market_slugs=current,
            ),
        ),
        next=(
            ()
            if not next_markets
            else (
                StreamRule(
                    StreamRelation.INDEPENDENT,
                    market_slugs=next_markets,
                ),
            )
        ),
    )


def _recording_market(
    slug: str,
    *,
    resolved: bool = False,
) -> RecordingMarket:
    condition_id = f"condition-{slug}"
    token_ids = (f"{slug}-up", f"{slug}-down")
    winning_token_id = token_ids[0] if resolved else None
    winning_outcome = "Up" if resolved else None
    market = Market(
        condition_id=condition_id,
        slug=slug,
        question=f"Will {slug} go up?",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0.02"),
        outcomes=(
            MarketOutcome("Up", token_ids[0]),
            MarketOutcome("Down", token_ids[1]),
        ),
        resolved=resolved,
        winning_token_id=winning_token_id,
        winning_outcome=winning_outcome,
    )
    metadata = MarketMetadataPayload(
        market_id=f"market-{slug}",
        condition_id=condition_id,
        market_slug=slug,
        question=market.question,
        events=(),
        outcomes=(
            MarketOutcomeMetadata("Up", token_ids[0]),
            MarketOutcomeMetadata("Down", token_ids[1]),
        ),
        active=not resolved,
        closed=resolved,
        archived=False,
        start_at_ms=0,
        end_at_ms=None,
        closed_at_ms=None,
        order_book_enabled=True,
        accepting_orders=not resolved,
        minimum_tick_size=market.minimum_tick_size,
        minimum_order_size=market.minimum_order_size,
        seconds_delay=0,
        neg_risk=market.neg_risk,
        fees_enabled=True,
        fee_type=None,
        fee_schedule=None,
        fee_rate=market.fee_rate,
        question_id=None,
        neg_risk_request_id=None,
        resolution_status="resolved" if resolved else None,
        resolution_source=None,
        resolved_by=None,
        resolved=resolved,
        winning_token_id=winning_token_id,
        winning_outcome=winning_outcome,
    )
    return RecordingMarket(market=market, metadata=metadata)


def _baseline_payload(token_id: str) -> BookBaselinePayload:
    return BookBaselinePayload(
        token_id=token_id,
        bids=(RecordedBookLevel(Decimal("0.40"), Decimal("2")),),
        asks=(RecordedBookLevel(Decimal("0.60"), Decimal("3")),),
        source_hash=f"hash-{token_id}",
    )


def _baseline_event(
    recording: RecordingMarket,
    token_index: int,
    source_timestamp_ms: int,
) -> CapturedMarketEvent:
    token_id = recording.market.token_ids[token_index]
    return CapturedMarketEvent(
        source_timestamp_ms=source_timestamp_ms,
        identity=MarketIdentity(
            condition_id=recording.market.condition_id,
            market_slug=recording.market.slug,
            token_id=token_id,
        ),
        payload=_baseline_payload(token_id),
    )


def _delta_event(
    recording: RecordingMarket,
    price: str,
    source_timestamp_ms: int,
) -> CapturedMarketEvent:
    token_id = recording.market.token_ids[0]
    return CapturedMarketEvent(
        source_timestamp_ms=source_timestamp_ms,
        identity=MarketIdentity(
            condition_id=recording.market.condition_id,
            market_slug=recording.market.slug,
        ),
        payload=BookDeltaPayload(
            changes=(
                BookChange(
                    token_id=token_id,
                    side=Side.BUY,
                    price=Decimal(price),
                    size=Decimal("1"),
                    source_hash=f"hash-{price}",
                ),
            )
        ),
    )


def _capture_continuity_error(
    recording: RecordingMarket,
) -> CaptureContinuityError:
    market = recording.market
    token_id = market.token_ids[0]
    identity = MarketIdentity(
        condition_id=market.condition_id,
        market_slug=market.slug,
    )
    first = CapturedMarketEvent(
        source_timestamp_ms=12,
        identity=identity,
        payload=BookDeltaPayload(
            changes=(
                BookChange(
                    token_id=token_id,
                    side=Side.BUY,
                    price=Decimal("0.61"),
                    size=Decimal("1"),
                    source_hash="revision-hash",
                    best_bid=Decimal("0.61"),
                    best_ask=Decimal("0.60"),
                ),
            )
        ),
    )
    mismatch = CapturedMarketEvent(
        source_timestamp_ms=12,
        identity=identity,
        payload=BookDeltaPayload(
            changes=(
                BookChange(
                    token_id=token_id,
                    side=Side.BUY,
                    price=Decimal("0.62"),
                    size=Decimal("1"),
                    source_hash="different-hash",
                    best_bid=Decimal("0.62"),
                    best_ask=Decimal("0.60"),
                ),
            )
        ),
    )
    projected_books = tuple(
        BookSnapshot(
            token_id=outcome.token_id,
            bids=(BookLevel(Decimal("0.40"), Decimal("2")),),
            asks=(BookLevel(Decimal("0.60"), Decimal("3")),),
            received_at_ms=12,
            market_slug=market.slug,
            condition_id=market.condition_id,
            outcome=outcome.label,
        )
        for outcome in market.outcomes
    )
    return CaptureContinuityError(
        MarketDataError(MarketDataIssue.CROSSED_BOOK, "projected book crossed"),
        failure_kind=CaptureFailureKind.SPLIT_REVISION_MISMATCH,
        first_fragment=first,
        matching_fragments=(),
        mismatching_fragment=mismatch,
        expected_fingerprint=RevisionFingerprint(
            condition_id=market.condition_id,
            source_timestamp_ms=12,
            source_hashes=((token_id, "revision-hash"),),
        ),
        actual_fingerprint=RevisionFingerprint(
            condition_id=market.condition_id,
            source_timestamp_ms=12,
            source_hashes=((token_id, "different-hash"),),
        ),
        projected_books=projected_books,
        dropped_count_before=0,
        dropped_count_after=0,
        elapsed_seconds=0.012,
    )


def _resolution_event(
    recording: RecordingMarket,
    source_timestamp_ms: int,
) -> CapturedMarketEvent:
    return CapturedMarketEvent(
        source_timestamp_ms=source_timestamp_ms,
        identity=MarketIdentity(
            condition_id=recording.market.condition_id,
            market_slug=recording.market.slug,
        ),
        payload=ResolutionPayload(
            token_ids=recording.market.token_ids,
            winning_token_id=recording.market.token_ids[0],
            winning_outcome=recording.market.outcomes[0].label,
            source="market_websocket",
        ),
    )


async def _wait_for(
    predicate: Callable[[], bool],
    *,
    timeout: float = 1.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not reached before test timeout")
        await asyncio.sleep(0.001)
