import asyncio
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.examples.example_dynamic_random_hold import (
    DYNAMIC_RANDOM_HOLD_ORDER_SIZE,
    ExampleDynamicRandomHoldBot,
    create,
)
from polybot.examples.btc_five_minute_market import (
    BTC_FIVE_MINUTE_BUCKET_SECONDS,
    BTC_FIVE_MINUTE_SLUG_PREFIX,
)
from polybot.framework.markets import market_bucket_slug


def test_dynamic_random_hold_factory_uses_its_fixed_order_size() -> None:
    assert create().order_size == DYNAMIC_RANDOM_HOLD_ORDER_SIZE


def test_dynamic_random_hold_bot_declares_current_and_next_buckets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[tuple[str, ...], tuple[str, ...]]:
        bot = ExampleDynamicRandomHoldBot(
            BTC_FIVE_MINUTE_SLUG_PREFIX,
            bucket_seconds=BTC_FIVE_MINUTE_BUCKET_SECONDS,
            hold_seconds=5,
            order_size=Decimal("1"),
        )
        current = await bot.current_stream_rules(dummy_context, now_ms=0)
        following = await bot.next_stream_rules(dummy_context, now_ms=0)
        return current[0].market_slugs, following[0].market_slugs

    current, following = asyncio.run(run())

    assert current == (
        market_bucket_slug(
            BTC_FIVE_MINUTE_SLUG_PREFIX,
            0,
            BTC_FIVE_MINUTE_BUCKET_SECONDS,
        ),
    )
    assert following == (
        market_bucket_slug(
            BTC_FIVE_MINUTE_SLUG_PREFIX,
            0,
            BTC_FIVE_MINUTE_BUCKET_SECONDS,
            bucket_offset=1,
        ),
    )
