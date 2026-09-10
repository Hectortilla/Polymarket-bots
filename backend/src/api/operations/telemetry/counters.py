"""Atomic, expiring HTTP observation counters and strict Redis value ingress."""

from time import time

from redis.asyncio import Redis

from api.operations.observations.contracts import Observation
from api.operations.telemetry.errors import TelemetryDataError
from api.operations.telemetry.keys import OPERATIONS_TELEMETRY_KEY_NAMESPACE

METRIC_WINDOW_SECONDS = 60
METRIC_TTL_SECONDS = METRIC_WINDOW_SECONDS * 3
MAX_METRIC_COUNT = 2**63 - 1
COUNTER_KEY_PREFIX = OPERATIONS_TELEMETRY_KEY_NAMESPACE + "counter:"
INCREMENT_COUNTER_SCRIPT = """
local value = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[1])
return value
"""


class ObservationCounters:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def increment(self, event: Observation) -> None:
        await self._redis.eval(
            INCREMENT_COUNTER_SCRIPT,
            1,
            self.key(event, self.current_bucket()),
            METRIC_TTL_SECONDS,
        )

    async def recent_count(self, event: Observation) -> int:
        bucket = self.current_bucket()
        values = await self._redis.mget(
            [self.key(event, bucket), self.key(event, bucket - 1)]
        )
        return sum(self._parse_value(value) for value in values)

    @staticmethod
    def current_bucket() -> int:
        return int(time()) // METRIC_WINDOW_SECONDS

    @staticmethod
    def key(event: Observation, bucket: int) -> str:
        return f"{COUNTER_KEY_PREFIX}{event}:{bucket}"

    @staticmethod
    def _parse_value(value: bytes | None) -> int:
        if value is None:
            return 0
        try:
            count = int(value)
        except (TypeError, ValueError):
            raise TelemetryDataError from None
        if not 0 <= count <= MAX_METRIC_COUNT:
            raise TelemetryDataError
        return count
