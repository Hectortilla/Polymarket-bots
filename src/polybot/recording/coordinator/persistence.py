"""Durable archive mutations used by the recording coordinator."""

from __future__ import annotations

import asyncio

from polybot.polymarket.recording_feed.continuity import CaptureContinuityError
from polybot.polymarket.recording_metadata.contracts import RecordingMarket
from polybot.polymarket.resolution import GAMMA_RECONCILIATION_SOURCE
from polybot.recording.clock import ObservationClock
from polybot.recording.contracts.book import BookBaselinePayload
from polybot.recording.contracts.gaps import (
    CoverageGapPayload,
    CoverageGapReason,
)
from polybot.recording.contracts.market import MarketIdentity
from polybot.recording.contracts.payloads import ResolutionPayload
from polybot.recording.writer import AsyncRecordingWriter
from polybot.recording.writer_contracts import (
    RecordingCheckpointWrite,
    RecordingEventWrite,
)

from .anomalies import create_capture_anomaly_payload
from .state import TrackedMarket


class RecordingPersistence:
    """Serialize metadata, integrity, and checkpoint writes for captures."""

    def __init__(
        self,
        writer: AsyncRecordingWriter,
        clock: ObservationClock,
        lock: asyncio.Lock,
    ) -> None:
        self._writer = writer
        self._clock = clock
        self._lock = lock

    async def record_initial_metadata(self, tracked: TrackedMarket) -> None:
        """Persist the first metadata revision for a newly tracked condition."""
        async with self._lock:
            observed_at_ms = self._clock.now_ms()
            await self._writer.record(
                tracked.recording.metadata,
                observed_at_ms=observed_at_ms,
                source_timestamp_ms=None,
                identity=self._market_identity(tracked.recording),
                subscription_generation=0,
            )
            tracked.last_observed_at_ms = max(
                tracked.last_observed_at_ms,
                observed_at_ms,
            )

    async def record_metadata(
        self,
        tracked: TrackedMarket,
        recording: RecordingMarket,
    ) -> None:
        """Persist a compatible metadata revision and make it current."""
        tracked.recording.assert_compatible_revision(recording)
        async with self._lock:
            observed_at_ms = self._clock.now_ms()
            await self._writer.record(
                recording.metadata,
                observed_at_ms=observed_at_ms,
                source_timestamp_ms=None,
                identity=self._market_identity(recording),
                subscription_generation=tracked.generation,
            )
            tracked.recording = recording
            tracked.last_observed_at_ms = max(
                tracked.last_observed_at_ms,
                observed_at_ms,
            )

    async def record_gamma_resolution(
        self,
        tracked: TrackedMarket,
        recording: RecordingMarket,
    ) -> int | None:
        """Atomically persist a Gamma-confirmed winner and metadata revision."""
        tracked.recording.assert_compatible_revision(recording)
        market = recording.market
        if (
            not recording.metadata.resolved
            or market.winning_token_id is None
            or market.winning_outcome is None
        ):
            raise ValueError("resolved metadata does not identify a winner")
        async with self._lock:
            if tracked.terminal_claimed:
                return None
            tracked.terminal_claimed = True
            observed_at_ms = self._clock.now_ms()
            writes: list[RecordingEventWrite] = []
            if recording.metadata != tracked.recording.metadata:
                writes.append(
                    RecordingEventWrite(
                        payload=recording.metadata,
                        observed_at_ms=observed_at_ms,
                        source_timestamp_ms=None,
                        identity=self._market_identity(recording),
                        subscription_generation=tracked.generation,
                    )
                )
            writes.append(
                RecordingEventWrite(
                    payload=ResolutionPayload(
                        token_ids=market.token_ids,
                        winning_token_id=market.winning_token_id,
                        winning_outcome=market.winning_outcome,
                        source=GAMMA_RECONCILIATION_SOURCE,
                    ),
                    observed_at_ms=observed_at_ms,
                    source_timestamp_ms=None,
                    identity=MarketIdentity(
                        condition_id=market.condition_id,
                        market_slug=market.slug,
                    ),
                    subscription_generation=tracked.generation,
                )
            )
            await self._writer.record_batch(tuple(writes))
            tracked.recording = recording
            tracked.last_observed_at_ms = max(
                tracked.last_observed_at_ms,
                observed_at_ms,
            )
            return observed_at_ms

    async def record_capture_anomaly(
        self,
        tracked: TrackedMarket,
        error: CaptureContinuityError,
    ) -> None:
        """Journal a malformed split revision before restarting its capture."""
        market = tracked.recording.market
        async with self._lock:
            await self._writer.record_anomaly(
                create_capture_anomaly_payload(error),
                observed_at_ms=self._clock.now_ms(),
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.slug,
                ),
                subscription_generation=tracked.generation,
            )

    async def open_gap(
        self,
        tracked: TrackedMarket,
        *,
        reason: CoverageGapReason,
        started_at_ms: int,
        details: str | None,
    ) -> None:
        """Open the one active coverage gap for a condition when needed."""
        if tracked.gap_ids:
            return
        market = tracked.recording.market
        async with self._lock:
            gap = await self._writer.open_gap(
                CoverageGapPayload(
                    reason=reason,
                    started_at_ms=started_at_ms,
                    ended_at_ms=None,
                    affected_condition_ids=(market.condition_id,),
                    affected_market_slugs=(market.slug,),
                    affected_token_ids=market.token_ids,
                    details=details,
                ),
                observed_at_ms=self._clock.now_ms(),
                identity=MarketIdentity(
                    condition_id=market.condition_id,
                    market_slug=market.slug,
                ),
                subscription_generation=tracked.generation,
            )
            tracked.gap_ids.add(gap.gap_id)

    async def close_gaps(
        self,
        gap_ids: tuple[int, ...],
        *,
        ended_at_ms: int,
    ) -> None:
        """Close already selected coverage gaps at a common recovery time."""
        for gap_id in gap_ids:
            await self._writer.close_gap(gap_id, ended_at_ms=ended_at_ms)

    async def write_checkpoint_batch(
        self,
        tracked_markets: tuple[TrackedMarket, ...],
    ) -> None:
        """Persist a same-timestamp checkpoint batch for eligible captures."""
        if not tracked_markets:
            return
        async with self._lock:
            observed_at_ms = self._clock.now_ms()
            writes = tuple(
                write
                for tracked in tracked_markets
                for write in self._checkpoint_writes(tracked, observed_at_ms)
            )
            if writes:
                await self._writer.checkpoint_batch(writes)

    @staticmethod
    def _market_identity(recording: RecordingMarket) -> MarketIdentity:
        return MarketIdentity(
            condition_id=recording.metadata.condition_id,
            market_slug=recording.metadata.market_slug,
        )

    @staticmethod
    def _checkpoint_writes(
        tracked: TrackedMarket,
        observed_at_ms: int,
    ) -> tuple[RecordingCheckpointWrite, ...]:
        capture = tracked.capture
        projector = tracked.projector
        if capture is None or projector is None:
            raise AssertionError("checkpoint market has no active capture")
        return tuple(
            RecordingCheckpointWrite(
                book=BookBaselinePayload.from_snapshot(book),
                observed_at_ms=observed_at_ms,
                identity=MarketIdentity(
                    condition_id=book.condition_id,
                    market_slug=book.market_slug,
                    token_id=book.token_id,
                ),
                subscription_generation=capture.generation,
            )
            for book in projector.snapshots(received_at_ms=observed_at_ms)
        )
