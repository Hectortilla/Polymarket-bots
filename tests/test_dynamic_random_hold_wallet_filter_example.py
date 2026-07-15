import asyncio
from decimal import Decimal

import pytest

from polybot.examples.example_dynamic_random_hold_wallet_filter_copy import (
    ExampleDynamicRandomHoldWalletFilterBot,
)
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.wallet_trades import WalletTradeEvent
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


def test_wallet_filter_bot_tracks_positions_per_wallet_and_caps_sells(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[list[OrderRequest], dict[tuple[str, str, str], Decimal]]:
        bot = ExampleDynamicRandomHoldWalletFilterBot(
            "btc-updown-5m",
            wallet_addresses=WALLETS,
        )
        await bot.on_wallet_trade(dummy_context, _wallet_trade(wallet=WALLETS[0]))
        await bot.on_wallet_trade(
            dummy_context,
            _wallet_trade(wallet=WALLETS[0], side=Side.SELL, price=Decimal("0.80")),
        )
        await bot.on_wallet_trade(
            dummy_context,
            _wallet_trade(wallet=WALLETS[1], side=Side.SELL, price=Decimal("0.80")),
        )
        return dummy_context.broker.submitted, bot.open_positions

    orders, positions = asyncio.run(run())

    assert [order.side for order in orders] == [Side.BUY, Side.SELL]
    assert orders[0].size == Decimal("25")
    assert orders[1].size == Decimal("12.5")
    assert positions == {
        (WALLETS[0], "condition-id", "token-id"): Decimal("12.5")
    }


def _wallet_trade(
    *,
    wallet: str,
    side: Side = Side.BUY,
    price: Decimal = Decimal("0.40"),
) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet=wallet,
        condition_id="condition-id",
        token_id="token-id",
        side=side,
        size=Decimal("3"),
        price=price,
        source_id=f"{wallet}-{side.value}-{price}",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_001,
        market_slug="market-slug",
    )
