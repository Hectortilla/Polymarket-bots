"""Configured ownership of fixed live-shard connection pools."""

import asyncio
from functools import cached_property

from redis.asyncio import Redis

from api.deployment.settings import StartupSettings
from api.events.health.store import FeedHealthStore
from api.io_policy import REDIS_SOCKET_OPTIONS

from .policy import LIVE_REDIS_POOL_SIZE
from .routing import LiveShardRouter


class LiveConnections:
    def __init__(self, settings: StartupSettings) -> None:
        urls = tuple(url.get_secret_value() for url in settings.live_redis_urls) or (
            settings.redis_url.get_secret_value(),
        )
        self.router = LiveShardRouter(urls)
        self.clients = tuple(
            Redis.from_url(
                url, max_connections=LIVE_REDIS_POOL_SIZE, **REDIS_SOCKET_OPTIONS
            )
            for url in urls
        )

    @cached_property
    def health(self) -> FeedHealthStore:
        return FeedHealthStore(self.router, self.clients)

    async def close(self) -> None:
        await asyncio.gather(*(client.aclose() for client in self.clients))
