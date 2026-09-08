import asyncio
from decimal import Decimal

from polybot.examples.example_fixed_dollar_wallet_copy import (
    FixedDollarWalletCopyBot,
)
from polybot.examples.wallet_copy import (
    COPY_TRADE_NOTIONAL_USDC,
    FIXED_DOLLAR_COPY_REASON,
)
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.wallet_trades import WalletTradeEvent, wallet_source_key


def test_fixed_dollar_copy_preserves_requested_notional(dummy_context: BotContext) -> None:
    async def run() -> OrderRequest:
        bot = FixedDollarWalletCopyBot()
        await bot.on_wallet_trade(dummy_context, _wallet_trade(price=Decimal("0.40")))
        return dummy_context.broker.submitted[0]

    order = asyncio.run(run())

    assert order.size == Decimal("25")
    assert order.price * order.size == COPY_TRADE_NOTIONAL_USDC
    assert order.side is Side.BUY
    assert order.market_slug == "market-slug"
    assert order.condition_id == "condition-id"
    assert order.source_id == wallet_source_key("0xleader", "trade-id")
    assert order.reason == FIXED_DOLLAR_COPY_REASON


def test_fixed_dollar_copy_uses_the_same_notional_for_sells(dummy_context: BotContext) -> None:
    async def run() -> OrderRequest:
        bot = FixedDollarWalletCopyBot()
        await bot.on_wallet_trade(
            dummy_context,
            _wallet_trade(price=Decimal("0.80"), side=Side.SELL),
        )
        return dummy_context.broker.submitted[0]

    order = asyncio.run(run())

    assert order.size == Decimal("12.5")
    assert order.price * order.size == COPY_TRADE_NOTIONAL_USDC
    assert order.side is Side.SELL


def _wallet_trade(*, price: Decimal, side: Side = Side.BUY) -> WalletTradeEvent:
    return WalletTradeEvent(
        wallet="0xleader",
        condition_id="condition-id",
        token_id="token-id",
        side=side,
        size=Decimal("3"),
        price=price,
        source_id="trade-id",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_001,
        market_slug="market-slug",
    )
