"""Bounded latest-state publication; health and snapshots share fixed workers."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from api.events.contracts import LiveRunSnapshot
from api.events.contracts.payloads.lifecycle import FeedObservation
from api.events.health.store import FeedHealthStore

from .clock import ShardClock
from .contracts import LivePermit, PublishedSnapshot, RegisteredRun
from .metrics import LiveMetric, LiveMetrics
from .permits import LivePermitRefresher
from .policy import (
    LIVE_INTEREST_MAX_AGE_SECONDS,
    LIVE_MAX_IN_FLIGHT_PER_SHARD,
    LIVE_MAX_SNAPSHOT_BYTES,
    LIVE_REFRESH_BATCH_SIZE,
    LIVE_REFRESH_SECONDS,
)
from .redis import LiveRedisBoundary
from .routing import LiveShardRouter


@dataclass(slots=True)
class _RunSlot:
    registration: RegisteredRun
    snapshot: tuple[LiveRunSnapshot, LivePermit] | None = None
    health: tuple[FeedObservation, int, LivePermit] | None = None
    inflight: bool = False
    interested_until: float = 0

    def watched(self) -> bool:
        return monotonic() < self.interested_until


class LiveSnapshotPublisher:
    def __init__(
        self,
        router: LiveShardRouter,
        permits: LivePermitRefresher,
        redis: LiveRedisBoundary,
        health: FeedHealthStore,
        clocks: tuple[ShardClock, ...],
        metrics: LiveMetrics,
    ) -> None:
        self._router = router
        self._permits = permits
        self._redis = redis
        self._health = health
        self._clocks = clocks
        self.metrics = metrics
        self._slots: dict[UUID, _RunSlot] = {}
        self._ready = [asyncio.Event() for _ in router.shards]
        self._ready_ids: list[OrderedDict[UUID, None]] = [
            OrderedDict() for _ in router.shards
        ]
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._workers:
            return
        for shard in self._router.shards:
            self._workers.extend(
                asyncio.create_task(self._publish_worker(shard.index))
                for _ in range(LIVE_MAX_IN_FLIGHT_PER_SHARD)
            )
            self._workers.append(
                asyncio.create_task(self._refresh_interest(shard.index))
            )

    async def close(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._slots.clear()
        for ids in self._ready_ids:
            ids.clear()
        self.measure_slots()

    def register(self, registration: RegisteredRun) -> None:
        self._slots[registration.run_id] = _RunSlot(registration)

    def unregister(self, registration: RegisteredRun) -> None:
        slot = self._slot(registration)
        if slot is not None:
            self._slots.pop(registration.run_id)
            self._ready_ids[registration.shard_index].pop(registration.run_id, None)

    def watched(self, registration: RegisteredRun) -> bool:
        slot = self._slot(registration)
        return slot is not None and slot.watched()

    def submit(self, registration: RegisteredRun, snapshot: LiveRunSnapshot) -> bool:
        slot = self._slot(registration)
        permit = self._permits.permit_for(registration)
        if (
            slot is None
            or not slot.watched()
            or permit is None
            or snapshot.run_id != registration.run_id
            or snapshot.generation != registration.registration
        ):
            self.metrics.increment(LiveMetric.SUPPRESSED)
            return False
        if slot.snapshot is not None:
            self.metrics.increment(LiveMetric.COALESCED)
        # Capture authority at admission, not after a queued publication is delayed.
        slot.snapshot = snapshot, permit
        self._schedule(slot)
        return True

    def submit_health(
        self, registration: RegisteredRun, observation: FeedObservation, sequence: int
    ) -> bool:
        slot = self._slot(registration)
        permit = self._permits.permit_for(registration)
        if slot is None or permit is None:
            self.metrics.increment(LiveMetric.HEALTH_REJECTED)
            return False
        if slot.health is not None:
            if slot.health[0].observed_at >= observation.observed_at:
                return False
            self.metrics.increment(LiveMetric.COALESCED)
        slot.health = observation, sequence, permit
        self._schedule(slot)
        return True

    def measure_slots(self) -> None:
        self.metrics.gauge(
            LiveMetric.PENDING,
            sum(slot.snapshot is not None for slot in self._slots.values()),
        )
        self.metrics.gauge(
            LiveMetric.PENDING_HEALTH,
            sum(slot.health is not None for slot in self._slots.values()),
        )
        self.metrics.gauge(
            LiveMetric.INFLIGHT, sum(slot.inflight for slot in self._slots.values())
        )

    async def refresh_interest_once(self, shard_index: int) -> None:
        slots = tuple(
            slot
            for slot in self._slots.values()
            if slot.registration.shard_index == shard_index
        )
        for offset in range(0, len(slots), LIVE_REFRESH_BATCH_SIZE):
            batch = slots[offset : offset + LIVE_REFRESH_BATCH_SIZE]
            started = monotonic()
            try:
                channels = tuple(
                    self._router.channel(slot.registration.run_id) for slot in batch
                )
                counts = await self._redis.subscriber_counts(shard_index, channels)
            except Exception:
                self.metrics.increment(LiveMetric.INTEREST_FAILURE)
                for slot in batch:
                    slot.interested_until = 0
                continue
            for slot, channel in zip(batch, channels, strict=True):
                if self._slots.get(slot.registration.run_id) is slot:
                    slot.interested_until = (
                        started + LIVE_INTEREST_MAX_AGE_SECONDS
                        if counts.get(channel, 0) > 0
                        else 0
                    )

    async def _refresh_interest(self, shard_index: int) -> None:
        while True:
            started = monotonic()
            await self.refresh_interest_once(shard_index)
            await asyncio.sleep(max(0, LIVE_REFRESH_SECONDS - (monotonic() - started)))

    async def _publish_worker(self, shard_index: int) -> None:
        ready = self._ready[shard_index]
        ready_ids = self._ready_ids[shard_index]
        while True:
            await ready.wait()
            if not ready_ids:
                ready.clear()
                continue
            run_id, _ = ready_ids.popitem(last=False)
            if not ready_ids:
                ready.clear()
            slot = self._slots.get(run_id)
            if slot is None:
                continue
            snapshot, health = slot.snapshot, slot.health
            slot.snapshot = slot.health = None
            slot.inflight = True
            try:
                if snapshot is not None and slot.watched():
                    await self._publish_snapshot(*snapshot)
                if health is not None:
                    observation, sequence, permit = health
                    written = await self._health.record(
                        permit, observation, sequence, self._clocks[shard_index]
                    )
                    self.metrics.increment(
                        LiveMetric.HEALTH_WRITTEN
                        if written
                        else LiveMetric.HEALTH_REJECTED
                    )
            except Exception:
                self.metrics.increment(LiveMetric.REDIS_FAILURE)
            finally:
                slot.inflight = False
                if self._slots.get(run_id) is slot and (
                    slot.snapshot is not None or slot.health is not None
                ):
                    self._schedule(slot)

    async def _publish_snapshot(
        self, snapshot: LiveRunSnapshot, permit: LivePermit
    ) -> None:
        encoded = (
            PublishedSnapshot(
                snapshot=snapshot, publication_deadline_us=permit.redis_deadline_us
            )
            .model_dump_json()
            .encode()
        )
        if len(encoded) > LIVE_MAX_SNAPSHOT_BYTES:
            self.metrics.increment(LiveMetric.OVERSIZED)
            return
        started = monotonic()
        try:
            if await self._redis.publish(permit, encoded):
                self.metrics.increment(LiveMetric.PUBLISHED)
                self.metrics.increment(LiveMetric.PUBLISHED_BYTES, len(encoded))
            else:
                self.metrics.increment(LiveMetric.SUPPRESSED)
        finally:
            self.metrics.observe(LiveMetric.PUBLISH_SECONDS, monotonic() - started)

    def _slot(self, registration: RegisteredRun) -> _RunSlot | None:
        slot = self._slots.get(registration.run_id)
        return slot if slot is not None and slot.registration == registration else None

    def _schedule(self, slot: _RunSlot) -> None:
        if not slot.inflight:
            shard = slot.registration.shard_index
            self._ready_ids[shard][slot.registration.run_id] = None
            self._ready[shard].set()
