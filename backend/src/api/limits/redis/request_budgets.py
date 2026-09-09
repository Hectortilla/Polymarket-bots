"""Atomic per-account and global HTTP request budgets."""

from uuid import UUID

from redis.asyncio import Redis

from api.limits.policy import PAPER_BETA, RATE_WINDOW_SECONDS
from api.limits.redis.contracts import ResourceAdmissionOutcome, ResourceBucket

REQUEST_BUDGET_ADMISSION = f"""
local window = math.floor(tonumber(redis.call('TIME')[1]) / tonumber(ARGV[1]))
local outcomes = {{{ResourceAdmissionOutcome.USER_ALLOWANCE}, {ResourceAdmissionOutcome.GLOBAL_CAPACITY}}}
for i = 1, 2 do
    local key = KEYS[i] .. ':' .. window
    local count = redis.call('INCR', key)
    if count == 1 then redis.call('EXPIRE', key, ARGV[1]) end
    if count > tonumber(ARGV[i + 1]) then return outcomes[i] end
end
return {ResourceAdmissionOutcome.ACCEPTED}
"""


class RequestRateLimiter:
    def __init__(self, redis: Redis, user_id: UUID) -> None:
        self._redis = redis
        self._user_id = user_id

    async def consume_request_budget(self, *, expensive: bool) -> None:
        await self._consume_budget(
            ResourceBucket.REQUESTS,
            PAPER_BETA.requests_per_minute,
            PAPER_BETA.global_requests_per_minute,
        )
        if expensive:
            await self._consume_budget(
                ResourceBucket.EXPENSIVE,
                PAPER_BETA.expensive_requests_per_minute,
                PAPER_BETA.global_expensive_requests_per_minute,
            )

    async def _consume_budget(
        self, bucket: ResourceBucket, user_limit: int, global_limit: int
    ) -> None:
        keys = bucket.keys(self._user_id)
        result = await self._redis.eval(
            REQUEST_BUDGET_ADMISSION,
            len(keys),
            *keys,
            RATE_WINDOW_SECONDS,
            user_limit,
            global_limit,
        )
        ResourceAdmissionOutcome.from_redis(result).require_capacity("request")
