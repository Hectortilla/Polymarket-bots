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
        return self.market_bucket_slug(
            self.slug_prefix,
            now_ms,
            self.bucket_seconds,
            offset=offset,
        )

    @staticmethod
    def market_bucket_slug(
        prefix: str,
        now_ms: int,
        bucket_seconds: int,
        *,
        offset: int = 0,
    ) -> str:
        if bucket_seconds <= 0:
            raise ValueError("bucket_seconds must be positive")
        bucket_start = (now_ms // 1000 // bucket_seconds + offset) * bucket_seconds
        return f"{prefix}-{bucket_start}"