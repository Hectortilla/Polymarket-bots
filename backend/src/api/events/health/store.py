"""Shard-routed latest health reads and permit-gated atomic writes."""

from time import monotonic
from uuid import UUID

from polybot.framework.clock import system_now_utc
from pydantic import ValidationError
from redis.asyncio import Redis

from api.events.contracts.payloads.lifecycle import AvailableFeedHealth, FeedObservation
from api.events.health.contracts import FeedHealthRecord
from api.events.health.policy import FEED_KEY_PREFIX, FEED_TTL_SECONDS
from api.events.live.clock import MICROSECONDS_PER_SECOND, ShardClock
from api.events.live.contracts import LivePermit
from api.events.live.routing import LiveShardRouter

# Both deadline and observation ordering are checked where the delayed command
# executes. Retrying NOSCRIPT uses these original arguments, never a new permit.
_STORE_HEALTH = """
local parts = redis.call('TIME')
local redis_now_us = parts[1] * 1000000 + parts[2]
if redis_now_us >= tonumber(ARGV[1]) then return 0 end
local incoming = cjson.decode(ARGV[3])
if incoming.observed_at_us > redis_now_us then return 0 end
local existing = redis.call('GET', KEYS[1])
if existing then
    local ok, stored = pcall(cjson.decode, existing)
    if ok and type(stored) == 'table' and type(stored.observed_at_us) == 'number'
        and type(stored.generation) == 'number' and type(stored.sequence) == 'number' then
        if stored.observed_at_us >= incoming.observed_at_us then return 0 end
        if stored.generation > incoming.generation then return 0 end
        if stored.generation == incoming.generation and stored.sequence >= incoming.sequence then return 0 end
    end
end
local ttl_ms = math.floor((tonumber(ARGV[2]) - redis_now_us) / 1000)
if ttl_ms <= 0 then return 0 end
redis.call('PSETEX', KEYS[1], ttl_ms, ARGV[3])
return 1
"""


class FeedHealthStore:
    def __init__(self, router: LiveShardRouter, clients: tuple[Redis, ...]) -> None:
        self._router = router
        self._clients = clients
        self._scripts = tuple(
            client.register_script(_STORE_HEALTH) for client in clients
        )

    async def read(self, run_id: UUID) -> AvailableFeedHealth | None:
        client = self._clients[self._router.shard_for(run_id).index]
        value = await client.get(self.key(run_id))
        if value is None:
            return None
        try:
            record = FeedHealthRecord.model_validate_json(value, strict=True)
        except ValidationError:
            return None
        return record.observation.available_health(system_now_utc())

    async def record(
        self,
        permit: LivePermit,
        observation: FeedObservation,
        sequence: int,
        clock: ShardClock,
    ) -> bool:
        if not permit.valid_at(monotonic(), clock.epoch):
            return False
        observed_at_us = round(
            observation.observed_at.timestamp() * MICROSECONDS_PER_SECOND
        )
        record = FeedHealthRecord(
            generation=permit.registration,
            sequence=sequence,
            observed_at_us=observed_at_us,
            observation=observation,
        )
        try:
            result = await self._scripts[permit.shard_index](
                keys=[self.key(permit.run_id)],
                args=[
                    permit.redis_deadline_us,
                    observed_at_us + FEED_TTL_SECONDS * MICROSECONDS_PER_SECOND,
                    record.model_dump_json(),
                ],
            )
        except Exception:
            clock.invalidate()
            raise
        return bool(result)

    @staticmethod
    def key(run_id: UUID) -> str:
        return f"{FEED_KEY_PREFIX}{run_id}"
