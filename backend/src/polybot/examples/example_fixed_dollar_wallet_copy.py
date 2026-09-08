from __future__ import annotations

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.examples.wallet_copy import fixed_dollar_copy_order


class FixedDollarWalletCopyBot(BaseBot):
    """Copy each routed wallet trade with a fixed requested USDC notional."""

    def order_for_trade(self, trade: WalletTradeEvent) -> OrderRequest:
        return fixed_dollar_copy_order(trade)

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        await ctx.broker.submit(self.order_for_trade(trade))
