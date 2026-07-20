"""BTC five-minute bucket selection for market recording."""

from __future__ import annotations

from polybot.examples.btc_five_minute_strategy import (
    BTC_FIVE_MINUTE_BUCKET_SECONDS,
    BTC_FIVE_MINUTE_SLUG_PREFIX,
)
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.markets import market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule


class BtcFiveMinuteMarketBot(BaseBot):
    """Select the current and next BTC five-minute Up/Down markets."""

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
                    BTC_FIVE_MINUTE_SLUG_PREFIX,
                    now_ms,
                    BTC_FIVE_MINUTE_BUCKET_SECONDS,
                    bucket_offset=bucket_offset,
                ),
            ),
        )


def create() -> BtcFiveMinuteMarketBot:
    """Create the non-trading BTC five-minute recording target."""

    return BtcFiveMinuteMarketBot()
