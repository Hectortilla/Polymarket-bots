from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import OrderRequest, WalletTradeEvent


class ExampleWalletFollower(BaseBot):
    def __init__(
        self,
        leader_wallets: str | Iterable[str],
        size_multiplier: Decimal,
    ) -> None:
        if isinstance(leader_wallets, str):
            leader_wallets = (leader_wallets,)
        self.leader_wallets = frozenset(
            wallet.lower() for wallet in leader_wallets
        )
        self.size_multiplier = size_multiplier

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        if trade.wallet.lower() not in self.leader_wallets:
            return
        if trade.market_slug is None or trade.condition_id is None:
            return
        if trade.size <= 0 or trade.price <= 0:
            return

        await ctx.broker.submit(
            OrderRequest(
                token_id=trade.token_id,
                side=trade.side,
                price=trade.price,
                size=min(
                    trade.size * self.size_multiplier,
                    ctx.config.max_order_size,
                ),
                market_slug=trade.market_slug,
                condition_id=trade.condition_id,
                source_id=trade.source_id,
                reason="wallet_follow",
            )
        )
