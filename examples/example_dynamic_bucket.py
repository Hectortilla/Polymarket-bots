from __future__ import annotations

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.markets import MarketSubscription
from bots.framework.markets import market_bucket_slug


class ExampleFiveMinuteBucketBot(BaseBot):
    def __init__(self, slug_prefix: str, bucket_seconds: int = 300) -> None:
        self.slug_prefix = slug_prefix
        self.bucket_seconds = bucket_seconds

    async def current_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug_for(now_ms, bucket_offset=0)),)

    async def next_markets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[MarketSubscription, ...]:
        return (MarketSubscription(slug=self._slug_for(now_ms, bucket_offset=1)),)

    def _slug_for(self, now_ms: int, bucket_offset: int) -> str:
        return market_bucket_slug(
            self.slug_prefix,
            now_ms,
            self.bucket_seconds,
            bucket_offset=bucket_offset,
        )
