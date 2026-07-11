from __future__ import annotations

from polybot.framework.context import BotContext
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.examples.example_random_hold import ExampleRandomHoldBot


class ExampleDynamicRandomHoldBot(ExampleRandomHoldBot):
    """Random-hold example that follows consecutive time-bucket markets."""

    def __init__(
        self,
        slug_prefix: str,
        bucket_seconds: int = 300,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.slug_prefix = slug_prefix
        self.bucket_seconds = bucket_seconds

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=0),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=1),)

    def _stream_rule(self, now_ms: int, *, bucket_offset: int) -> StreamRule:
        return StreamRule(
            StreamRelation.INDEPENDENT,
            (
                market_bucket_slug(
                    self.slug_prefix,
                    now_ms,
                    self.bucket_seconds,
                    bucket_offset=bucket_offset,
                ),
            ),
        )
