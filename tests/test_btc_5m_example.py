from __future__ import annotations

import asyncio

from polybot.examples.btc_5m import BtcFiveMinuteMarketBot, create
from polybot.examples.btc_five_minute_strategy import BTC_FIVE_MINUTE_SLUG_PREFIX
from polybot.framework.context import BotContext


def test_btc_five_minute_recording_target_selects_current_and_next_buckets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, str]:
        bot = BtcFiveMinuteMarketBot()
        current = await bot.current_stream_rules(dummy_context, 1_783_549_320_000)
        following = await bot.next_stream_rules(dummy_context, 1_783_549_320_000)
        return current[0].market_slugs[0], following[0].market_slugs[0]

    current_slug, next_slug = asyncio.run(run())

    assert current_slug == f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-1783549200"
    assert next_slug == f"{BTC_FIVE_MINUTE_SLUG_PREFIX}-1783549500"


def test_btc_five_minute_recording_target_factory() -> None:
    assert isinstance(create(), BtcFiveMinuteMarketBot)
