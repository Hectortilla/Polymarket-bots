import asyncio
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.examples.example_dynamic_random_hold import ExampleDynamicRandomHoldBot


def test_dynamic_random_hold_bot_declares_current_and_next_buckets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[tuple[str, ...], tuple[str, ...]]:
        bot = ExampleDynamicRandomHoldBot(
            "btc-updown-5m",
            bucket_seconds=300,
            hold_seconds=5,
            order_size=Decimal("1"),
        )
        current = await bot.current_stream_rules(dummy_context, now_ms=0)
        following = await bot.next_stream_rules(dummy_context, now_ms=0)
        return current[0].market_slugs, following[0].market_slugs

    current, following = asyncio.run(run())

    assert current == ("btc-updown-5m-0",)
    assert following == ("btc-updown-5m-300",)
