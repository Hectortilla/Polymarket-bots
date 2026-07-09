import asyncio
from dataclasses import replace
from decimal import Decimal

from bots.examples.example_wallet_follower import ExampleWalletFollower
from bots.framework.context import BotContext
from bots.framework.events import OrderRequest, Side, WalletTradeEvent


def test_wallet_follower_carries_source_id(dummy_context: BotContext) -> None:
    async def run() -> OrderRequest:
        bot = ExampleWalletFollower("0xLeader", Decimal("0.5"))
        await bot.on_wallet_trade(dummy_context, _wallet_trade())
        return dummy_context.broker.submitted[0]

    order = asyncio.run(run())

    assert order.token_id == "123"
    assert order.side is Side.BUY
    assert order.size == Decimal("2.5")
    assert order.condition_id == "0xcondition"
    assert order.market_slug == "btc"
    assert order.source_id == "tx-1"
    assert order.reason == "wallet_follow"


def test_wallet_follower_ignores_non_leader(dummy_context: BotContext) -> None:
    async def run() -> int:
        bot = ExampleWalletFollower("0xLeader", Decimal("0.5"))
        trade = replace(_wallet_trade(), wallet="0xother")
        await bot.on_wallet_trade(dummy_context, trade)
        return len(dummy_context.broker.submitted)

    assert asyncio.run(run()) == 0


def test_wallet_follower_ignores_malformed_trade(dummy_context: BotContext) -> None:
    async def run() -> int:
        bot = ExampleWalletFollower("0xLeader", Decimal("0.5"))
        trade = replace(_wallet_trade(), market_slug=None, condition_id=None, size=Decimal("0"))
        await bot.on_wallet_trade(
            dummy_context,
            trade,
        )
        return len(dummy_context.broker.submitted)

    assert asyncio.run(run()) == 0


def _wallet_trade() -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet="0xleader",
        condition_id="0xcondition",
        token_id="123",
        side=Side.BUY,
        size=Decimal("5"),
        price=Decimal("0.42"),
        source_id="tx-1",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_250,
        market_slug="btc",
        transaction_hash="0xtx",
    )
