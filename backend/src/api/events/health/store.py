"""Redis health ingress distinguishes missing/invalid input from transport failures."""

from uuid import UUID

from polybot.framework.clock import system_now_utc
from pydantic import ValidationError
from redis.asyncio import Redis

from api.events.contracts import LiveStreamHealthEvent
from api.events.health.contracts import AvailableFeedHealth, FeedObservation
from api.events.health.policy import FEED_KEY_PREFIX, FEED_TTL_SECONDS


class FeedHealthStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def record(self, event: LiveStreamHealthEvent) -> None:
        observation = FeedObservation(
            observed_at=event.occurred_at, health=event.payload
        )
        await self._redis.set(
            self.key(event.run_id), observation.model_dump_json(), ex=FEED_TTL_SECONDS
        )

    async def read(self, run_id: UUID) -> AvailableFeedHealth | None:
        value = await self._redis.get(self.key(run_id))
        if value is None:
            return None
        try:
            observation = FeedObservation.model_validate_json(value, strict=True)
        except ValidationError:
            return None
        return observation.available_health(system_now_utc())

    @staticmethod
    def key(run_id: UUID) -> str:
        return f"{FEED_KEY_PREFIX}{run_id}"
