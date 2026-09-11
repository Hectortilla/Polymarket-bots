from __future__ import annotations

from polybot.examples.wallet_copy import FixedDollarCopyPolicy
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent


class FixedDollarWalletCopyBot(BaseBot):
    """Copy each routed wallet trade with a fixed requested USDC notional."""

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        await ctx.broker.submit(self.order_for_trade(trade))

    def order_for_trade(self, trade: WalletTradeEvent) -> OrderRequest:
        return FixedDollarCopyPolicy.order(trade)
