"""Expiring worker process presence, validated before availability decisions."""

from uuid import UUID

from redis.asyncio import Redis

from api.operations.telemetry.errors import TelemetryDataError
from api.operations.telemetry.keys import OPERATIONS_TELEMETRY_KEY_NAMESPACE
from api.operations.telemetry.presence_policy import (
    PRESENCE_TTL_SECONDS,
)

WORKER_KEY_PREFIX = OPERATIONS_TELEMETRY_KEY_NAMESPACE + "worker:"
WORKER_PRESENCE_MARKER = b"1"
READ_PRESENCE_SCRIPT = "return {redis.call('GET', KEYS[1]), redis.call('TTL', KEYS[1])}"


class WorkerPresenceStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def refresh(self, worker_id: UUID) -> None:
        await self._redis.set(
            self.key(worker_id), WORKER_PRESENCE_MARKER, ex=PRESENCE_TTL_SECONDS
        )

    async def remove(self, worker_id: UUID) -> None:
        await self._redis.delete(self.key(worker_id))

    async def count(self) -> int:
        live_worker_count = 0
        async for key in self._redis.scan_iter(WORKER_KEY_PREFIX + "*"):
            marker, ttl = await self._redis.eval(READ_PRESENCE_SCRIPT, 1, key)
            if marker is None:
                continue  # The key disappeared after SCAN.
            self._validate_presence(key, marker, ttl)
            live_worker_count += 1
        return live_worker_count

    @staticmethod
    def key(worker_id: UUID) -> str:
        return f"{WORKER_KEY_PREFIX}{worker_id}"

    @staticmethod
    def _validate_presence(key: bytes, marker: bytes, ttl: int) -> None:
        try:
            suffix = key.decode("ascii").removeprefix(WORKER_KEY_PREFIX)
            if (
                str(UUID(suffix)) != suffix
                or marker != WORKER_PRESENCE_MARKER
                or not 0 <= ttl <= PRESENCE_TTL_SECONDS
            ):
                raise TelemetryDataError
        except (UnicodeError, ValueError, TypeError):
            raise TelemetryDataError from None
