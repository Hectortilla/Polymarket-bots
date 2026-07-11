from __future__ import annotations

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule


class ExampleFiveMinuteBucketBot(BaseBot):
    def __init__(self, slug_prefix: str, bucket_seconds: int = 300) -> None:
        self.slug_prefix = slug_prefix
        self.bucket_seconds = bucket_seconds

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (StreamRule(StreamRelation.INDEPENDENT, (self._slug_for(now_ms, 0),)),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (StreamRule(StreamRelation.INDEPENDENT, (self._slug_for(now_ms, 1),)),)

    def _slug_for(self, now_ms: int, bucket_offset: int) -> str:
        return market_bucket_slug(
            self.slug_prefix,
            now_ms,
            self.bucket_seconds,
            bucket_offset=bucket_offset,
        )
