"""One task owns a multiplexed Pub/Sub connection and its subscription commands."""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from redis.asyncio import Redis

from api.events.live.metrics import LiveMetric, LiveMetrics
from api.events.live.policy import LIVE_POLL_SECONDS, LIVE_RECONNECT_MAX_SECONDS
from api.io_policy import DEPENDENCY_TIMEOUT_SECONDS


class SubscriptionLane:
    def __init__(
        self,
        redis: Redis,
        receive: Callable[[dict], None],
        disconnected: Callable[[], None],
        metrics: LiveMetrics,
    ) -> None:
        self._redis = redis
        self._receive = receive
        self._disconnected = disconnected
        self._metrics = metrics
        self._desired: set[str] = set()
        self._subscribed: set[str] = set()
        self._changed = asyncio.Event()
        self._applied = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self.connected = False

    @property
    def watching(self) -> bool:
        return bool(self._desired)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._serve())

    def add(self, channel: str) -> None:
        if self._closed:
            raise RuntimeError("subscription lane is closed")
        if channel not in self._desired:
            self._desired.add(channel)
            self._changed.set()

    def remove(self, channel: str) -> None:
        if channel in self._desired:
            self._desired.remove(channel)
            self._changed.set()
            self._applied.set()

    async def ready(self, channel: str) -> None:
        async with asyncio.timeout(DEPENDENCY_TIMEOUT_SECONDS):
            while channel not in self._subscribed:
                if self._closed or channel not in self._desired:
                    raise RuntimeError("subscription cancelled")
                self._applied.clear()
                await self._applied.wait()

    async def close(self) -> None:
        self._closed = True
        self._applied.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._desired.clear()

    async def _serve(self) -> None:
        backoff = LIVE_POLL_SECONDS
        while True:
            if not self._desired:
                self._changed.clear()
                await self._changed.wait()
                continue
            pubsub = self._redis.pubsub()
            requested: set[str] = set()
            self._changed.set()
            try:
                while self._desired:
                    # Reconcile membership only on a change, never per frame.
                    if self._changed.is_set():
                        self._changed.clear()
                        desired = self._desired.copy()
                        added = desired - requested
                        removed = requested - desired
                        if added:
                            await pubsub.subscribe(*sorted(added))
                        if removed:
                            await pubsub.unsubscribe(*sorted(removed))
                        requested = desired
                        self.connected = True
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=False, timeout=LIVE_POLL_SECONDS
                    )
                    backoff = LIVE_POLL_SECONDS
                    if message is not None:
                        self._message(message)
            except Exception:
                self._subscribed.clear()
                self.connected = False
                self._metrics.increment(LiveMetric.REDIS_FAILURE)
                self._metrics.increment(LiveMetric.RECONNECT)
                self._disconnected()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, LIVE_RECONNECT_MAX_SECONDS)
            finally:
                self._subscribed.clear()
                self.connected = False
                self._applied.set()
                with suppress(Exception):
                    await pubsub.aclose()

    def _message(self, message: dict) -> None:
        kind = message.get("type")
        if kind in {"subscribe", "unsubscribe"}:
            channel = message["channel"]
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")
            if kind == "subscribe":
                self._subscribed.add(channel)
            else:
                self._subscribed.discard(channel)
            # A socket write is not proof that Redis applied the subscription.
            self._applied.set()
        elif kind == "message":
            self._receive(message)
