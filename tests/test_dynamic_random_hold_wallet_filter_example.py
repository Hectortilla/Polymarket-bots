import asyncio

import pytest

from polybot.examples.example_dynamic_random_hold_wallet_filter_copy import (
    ExampleDynamicRandomHoldWalletFilterBot,
)
from polybot.framework.context import BotContext
from polybot.framework.streams import StreamRelation, StreamRule

WALLETS = (
    "0x0000000000000000000000000000000000000001",
    "0x0000000000000000000000000000000000000002",
)


def test_wallet_filter_bot_declares_filtered_current_and_next_buckets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[tuple[StreamRule, ...], tuple[StreamRule, ...]]:
        bot = ExampleDynamicRandomHoldWalletFilterBot(
            "btc-updown-5m",
            wallet_addresses=WALLETS,
        )
        return (
            await bot.current_stream_rules(dummy_context, now_ms=0),
            await bot.next_stream_rules(dummy_context, now_ms=0),
        )

    current, following = asyncio.run(run())

    assert current[0].relation is StreamRelation.FILTERED
    assert following[0].relation is StreamRelation.FILTERED
    assert current[0].market_slugs == ("btc-updown-5m-0",)
    assert current[0].wallet_addresses == WALLETS
    assert following[0].market_slugs == ("btc-updown-5m-300",)
    assert following[0].wallet_addresses == WALLETS


def test_wallet_filter_bot_requires_wallets() -> None:
    with pytest.raises(ValueError, match="wallet_addresses must contain at least one wallet"):
        ExampleDynamicRandomHoldWalletFilterBot("btc-updown-5m", ())
