"""Atomic open-stream reservations with bounded lifetime and explicit release."""

from time import monotonic
from uuid import UUID, uuid4

from redis.asyncio import Redis

from api.limits.policy import PAPER_BETA, STREAM_LEASE_SECONDS, STREAM_LIFETIME_SECONDS
from api.limits.redis.contracts import ResourceAdmissionOutcome, ResourceBucket

OPEN_STREAM_LEASE_ADMISSION = f"""
local now = tonumber(redis.call('TIME')[1])
for i = 1, 2 do redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now) end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return {ResourceAdmissionOutcome.USER_ALLOWANCE} end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[2]) then return {ResourceAdmissionOutcome.GLOBAL_CAPACITY} end
for i = 1, 2 do
    redis.call('ZADD', KEYS[i], now + tonumber(ARGV[3]), ARGV[4])
    redis.call('EXPIRE', KEYS[i], ARGV[3])
end
return {ResourceAdmissionOutcome.ACCEPTED}
"""


class OpenStreamAdmission:
    def __init__(self, redis: Redis, user_id: UUID) -> None:
        self._redis = redis
        self._user_id = user_id

    async def acquire_stream(self) -> "StreamLease":
        keys = ResourceBucket.STREAMS.keys(self._user_id)
        lease_token = str(uuid4())
        # Start before Redis IO so latency cannot outlive the shared reservation.
        monotonic_deadline_seconds = monotonic() + STREAM_LIFETIME_SECONDS
        result = await self._redis.eval(
            OPEN_STREAM_LEASE_ADMISSION,
            len(keys),
            *keys,
            PAPER_BETA.open_streams,
            PAPER_BETA.global_open_streams,
            STREAM_LEASE_SECONDS,
            lease_token,
        )
        ResourceAdmissionOutcome.from_redis(result).require_capacity("open-stream")
        return StreamLease(self._redis, keys, lease_token, monotonic_deadline_seconds)


class StreamLease:
    def __init__(
        self,
        redis: Redis,
        keys: tuple[str, str],
        lease_token: str,
        monotonic_deadline_seconds: float,
    ) -> None:
        self._redis = redis
        self._keys = keys
        self._lease_token = lease_token
        self.monotonic_deadline_seconds = monotonic_deadline_seconds

    async def release(self) -> None:
        async with self._redis.pipeline(transaction=True) as transaction:
            for key in self._keys:
                transaction.zrem(key, self._lease_token)
            await transaction.execute()
