"""Atomic shared Redis limits, using the server's trusted client address."""

import hashlib

from redis.asyncio import Redis

from api.auth.policy import (
    AUTH_RATE_LIMIT_KEY_PREFIX,
    AUTH_RATE_WINDOW_SECONDS,
)
from api.http.protocol import MIN_RETRY_AFTER_SECONDS

RATE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('TTL', KEYS[1])}
"""


class AuthRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check(
        self, path: str, client_address: str, attempt_limit: int
    ) -> tuple[bool, int]:
        key = (
            AUTH_RATE_LIMIT_KEY_PREFIX
            + hashlib.sha256(f"{path}:{client_address}".encode()).hexdigest()
        )
        count, ttl = await self._redis.eval(
            RATE_SCRIPT, 1, key, AUTH_RATE_WINDOW_SECONDS
        )
        return count <= attempt_limit, max(MIN_RETRY_AFTER_SECONDS, ttl)
