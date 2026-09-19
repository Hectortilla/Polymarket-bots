"""Redis publication and viewer-interest ingress; no database dependency."""

from time import monotonic

from redis.asyncio import Redis

from .clock import ShardClock
from .contracts import LivePermit
from .routing import LiveShardRouter

_PUBLISH_IF_FRESH = """
local parts = redis.call('TIME')
local redis_now_us = parts[1] * 1000000 + parts[2]
if redis_now_us >= tonumber(ARGV[1]) then return -1 end
return redis.call('PUBLISH', KEYS[1], ARGV[2])
"""


class LiveRedisBoundary:
    def __init__(
        self,
        router: LiveShardRouter,
        clients: tuple[Redis, ...],
        clocks: tuple[ShardClock, ...],
    ) -> None:
        self._router = router
        self._clients = clients
        self._clocks = clocks
        self._publish_scripts = tuple(
            client.register_script(_PUBLISH_IF_FRESH) for client in clients
        )

    async def publish(self, permit: LivePermit, payload: bytes) -> bool:
        clock = self._clocks[permit.shard_index]
        if not permit.valid_at(monotonic(), clock.epoch):
            return False
        try:
            result = await self._publish_scripts[permit.shard_index](
                keys=[self._router.channel(permit.run_id)],
                args=[permit.redis_deadline_us, payload],
            )
        except Exception:
            clock.invalidate()
            raise
        return int(result) >= 0

    async def subscriber_counts(
        self, shard_index: int, channels: tuple[str, ...]
    ) -> dict[str, int]:
        response = await self._clients[shard_index].pubsub_numsub(*channels)
        return {
            channel.decode("utf-8") if isinstance(channel, bytes) else channel: int(
                count
            )
            for channel, count in response
        }
