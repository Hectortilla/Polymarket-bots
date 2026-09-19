"""API-owned live-shard and durable-wake subscription fanout."""

import asyncio
from collections import defaultdict
from functools import partial
from time import monotonic, time
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis

from api.events.channels import (
    decode_durable_wake_frame,
    run_event_channel,
    run_from_event_channel,
)
from api.events.live.clock import ShardClock
from api.events.live.contracts import PublishedSnapshot
from api.events.live.metrics import LiveMetric, LiveMetrics
from api.events.live.policy import (
    LIVE_MAX_SNAPSHOT_BYTES,
    LIVE_METRICS_SECONDS,
    LIVE_POLL_SECONDS,
    LIVE_REFRESH_SECONDS,
)
from api.events.live.routing import LiveShardRouter
from api.http.sse.frames import sse_frame
from api.http.sse.mailbox import LiveFrame, ViewerMailbox
from api.http.sse.subscriptions import SubscriptionLane


class LiveSubscriptionHub:
    def __init__(
        self, router: LiveShardRouter, redis_by_shard: tuple[Redis, ...], durable: Redis
    ) -> None:
        self._router, self._redis = router, redis_by_shard
        self.metrics = LiveMetrics()
        self._clocks = tuple(ShardClock() for _ in router.shards)
        self._viewers: dict[UUID, set[ViewerMailbox]] = defaultdict(set)
        self._identities: dict[UUID, tuple[int, int]] = {}
        self._terminal: set[UUID] = set()
        self._durable = SubscriptionLane(
            durable, self._receive_durable, self._durable_disconnected, self.metrics
        )
        self._live = tuple(
            SubscriptionLane(
                client,
                partial(self._receive_live, index),
                partial(self._live_disconnected, index),
                self.metrics,
            )
            for index, client in enumerate(redis_by_shard)
        )
        self._tasks: list[asyncio.Task[None]] = []
        self._closed = False

    async def start(self) -> None:
        if self._tasks:
            return
        self._durable.start()
        for index, lane in enumerate(self._live):
            lane.start()
            self._tasks.append(asyncio.create_task(self._sample_clock(index)))
        self._tasks.append(asyncio.create_task(self._report_metrics()))

    async def close(self) -> None:
        self._closed = True
        for viewers in self._viewers.values():
            for viewer in viewers:
                viewer.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await asyncio.gather(
            self._durable.close(), *(lane.close() for lane in self._live)
        )
        self._tasks.clear()
        self._viewers.clear()
        self._identities.clear()
        self._terminal.clear()

    async def attach(self, run_id: UUID) -> ViewerMailbox:
        if self._closed:
            raise RuntimeError("live subscription hub is closed")
        mailbox = ViewerMailbox()
        self._viewers[run_id].add(mailbox)
        live = self._live[self._router.shard_for(run_id).index]
        durable_channel, live_channel = (
            run_event_channel(run_id),
            self._router.channel(run_id),
        )
        self._durable.add(durable_channel)
        if run_id not in self._terminal:
            live.add(live_channel)
        else:
            mailbox.terminal()
        try:
            await self._durable.ready(durable_channel)
            if run_id not in self._terminal:
                try:
                    await live.ready(live_channel)
                except RuntimeError:
                    if run_id not in self._terminal:
                        raise
        except BaseException:
            await self.detach(run_id, mailbox)
            raise
        return mailbox

    async def detach(self, run_id: UUID, mailbox: ViewerMailbox) -> None:
        mailbox.close()
        viewers = self._viewers.get(run_id)
        if viewers is None:
            return
        viewers.discard(mailbox)
        if not viewers:
            self._viewers.pop(run_id)
            self._identities.pop(run_id, None)
            self._terminal.discard(run_id)
            self._durable.remove(run_event_channel(run_id))
            self._live[self._router.shard_for(run_id).index].remove(
                self._router.channel(run_id)
            )

    def terminal(self, run_id: UUID) -> None:
        if run_id in self._viewers:
            self._terminal.add(run_id)
            for viewer in self._viewers[run_id]:
                viewer.terminal()
            self._live[self._router.shard_for(run_id).index].remove(
                self._router.channel(run_id)
            )

    def is_terminal(self, run_id: UUID) -> bool:
        return run_id in self._terminal

    def _receive_durable(self, message: dict) -> None:
        if decode_durable_wake_frame(message.get("data")) is None:
            return
        run_id = run_from_event_channel(message.get("channel"))
        for viewer in tuple(self._viewers.get(run_id, ())):
            viewer.offer_durable_wake()

    def _receive_live(self, shard_index: int, message: dict) -> None:
        run_id = self._router.run_from_channel(message.get("channel"), shard_index)
        raw = message.get("data")
        if run_id not in self._viewers or run_id in self._terminal:
            return
        if (
            not isinstance(raw, (str, bytes))
            or len(raw.encode() if isinstance(raw, str) else raw)
            > LIVE_MAX_SNAPSHOT_BYTES
        ):
            self.metrics.increment(LiveMetric.INVALID_FRAME)
            return
        try:
            envelope = PublishedSnapshot.model_validate_json(raw, strict=True)
        except ValidationError:
            self.metrics.increment(LiveMetric.INVALID_FRAME)
            return
        snapshot, clock = envelope.snapshot, self._clocks[shard_index]
        identity = snapshot.generation, snapshot.sequence
        if (
            snapshot.run_id != run_id
            or identity <= self._identities.get(run_id, (0, 0))
            or not clock.fresh(envelope.publication_deadline_us)
        ):
            self.metrics.increment(LiveMetric.INVALID_FRAME)
            return
        self._identities[run_id] = identity
        frame = LiveFrame(
            sse_frame(snapshot).encode(),
            envelope.publication_deadline_us,
            clock,
            clock.epoch,
        )
        self.metrics.observe(
            LiveMetric.SNAPSHOT_AGE_SECONDS,
            max(0, time() - snapshot.sampled_at_ms / 1000),
        )
        for viewer in tuple(self._viewers[run_id]):
            viewer.offer_live(frame)

    def _durable_disconnected(self) -> None:
        for viewers in self._viewers.values():
            for viewer in viewers:
                viewer.offer_durable_wake()

    def _live_disconnected(self, shard_index: int) -> None:
        self._clocks[shard_index].invalidate()
        for run_id, viewers in self._viewers.items():
            if self._router.shard_for(run_id).index == shard_index:
                for viewer in viewers:
                    viewer.discard_live()

    async def _sample_clock(self, shard_index: int) -> None:
        while True:
            if not self._live[shard_index].watching:
                await asyncio.sleep(LIVE_POLL_SECONDS)
                continue
            try:
                await self._clocks[shard_index].sample(self._redis[shard_index])
            except Exception:
                self.metrics.increment(LiveMetric.REDIS_FAILURE)
                self._live_disconnected(shard_index)
            await asyncio.sleep(LIVE_REFRESH_SECONDS)

    async def _report_metrics(self) -> None:
        while True:
            deadline = monotonic() + LIVE_METRICS_SECONDS
            await asyncio.sleep(LIVE_METRICS_SECONDS)
            self.metrics.observe(
                LiveMetric.EVENT_LOOP_LAG_SECONDS, max(0, monotonic() - deadline)
            )
            self.metrics.gauge(
                LiveMetric.VIEWERS, sum(map(len, self._viewers.values()))
            )
            self.metrics.gauge(
                LiveMetric.SUBSCRIPTION_CONNECTIONS,
                int(self._durable.connected)
                + sum(lane.connected for lane in self._live),
            )
            self.metrics.emit("api")
