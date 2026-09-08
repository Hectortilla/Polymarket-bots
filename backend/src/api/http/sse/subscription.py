"""Own the Redis subscription lifetime, including failed subscriptions."""

from types import TracebackType
from uuid import UUID

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from api.events.channels import run_event_channel


class RunSubscription:
    def __init__(self, redis: Redis, run_id: UUID) -> None:
        self._pubsub = redis.pubsub()
        self._channel = run_event_channel(run_id)

    async def __aenter__(self) -> PubSub:
        try:
            await self._pubsub.subscribe(self._channel)
        except BaseException:
            await self._pubsub.aclose()
            raise
        return self._pubsub

    async def __aexit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            await self._pubsub.unsubscribe(self._channel)
        finally:
            await self._pubsub.aclose()
