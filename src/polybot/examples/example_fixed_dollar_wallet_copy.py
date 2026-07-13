from __future__ import annotations

from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest
from polybot.framework.events.wallet_trades import WalletTradeEvent

COPY_TRADE_NOTIONAL_USDC = Decimal("10")
FIXED_DOLLAR_COPY_REASON = "fixed_dollar_wallet_copy"


class FixedDollarWalletCopyBot(BaseBot):
    """Copy each routed wallet trade with a fixed requested USDC notional."""

    def order_for_trade(self, trade: WalletTradeEvent) -> OrderRequest:
        return OrderRequest(
            token_id=trade.token_id,
            side=trade.side,
            price=trade.price,
            size=COPY_TRADE_NOTIONAL_USDC / trade.price,
            market_slug=trade.market_slug,
            condition_id=trade.condition_id,
            source_id=trade.source_key,
            reason=FIXED_DOLLAR_COPY_REASON,
        )

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        await ctx.broker.submit(self.order_for_trade(trade))
