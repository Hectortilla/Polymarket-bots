from __future__ import annotations

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.markets import MarketSubscription


class ExampleFiveMinuteBucketBot(BaseBot):
    def __init__(self, slug_prefix: str, bucket_seconds: int = 300) -> None:
        self.slug_prefix = slug_prefix
        self.bucket_seconds = bucket_seconds

    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug_for(now_ms, offset=0)),)

    async def next_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug_for(now_ms, offset=1)),)

    def _slug_for(self, now_ms: int, offset: int) -> str:
        now_seconds = now_ms // 1000
        bucket = now_seconds // self.bucket_seconds + offset
        bucket_start = bucket * self.bucket_seconds
        return f"{self.slug_prefix}-{bucket_start}"
