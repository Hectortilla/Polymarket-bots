from __future__ import annotations

from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.examples.example_random_hold import ExampleRandomHoldBot


DYNAMIC_RANDOM_HOLD_ORDER_SIZE = Decimal("5")


class ExampleDynamicRandomHoldBot(ExampleRandomHoldBot):
    """Random-hold example that follows consecutive time-bucket markets."""

    def __init__(
        self,
        slug_prefix: str,
        bucket_seconds: int = 300,
        *,
        order_size: Decimal = DYNAMIC_RANDOM_HOLD_ORDER_SIZE,
        **kwargs: object,
    ) -> None:
        super().__init__(order_size=order_size, **kwargs)
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


def create() -> ExampleDynamicRandomHoldBot:
    """CLI factory."""
    return ExampleDynamicRandomHoldBot(slug_prefix="btc-updown-5m")
