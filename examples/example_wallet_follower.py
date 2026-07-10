from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import OrderRequest
from bots.framework.events.wallet_trades import WalletTradeEvent
from bots.framework.wallets import WalletSubscription, normalize_wallet_address

WALLET_FOLLOW_REASON = "wallet_follow"


class ExampleWalletFollower(BaseBot):
    def __init__(
        self,
        leader_wallets: str | Iterable[str],
        size_multiplier: Decimal,
    ) -> None:
        if isinstance(leader_wallets, str):
            leader_wallets = (leader_wallets,)
        self.leader_wallets = frozenset(
            normalize_wallet_address(wallet) for wallet in leader_wallets
        )
        self.size_multiplier = size_multiplier

    def order_for_trade(
        self,
        trade: WalletTradeEvent,
        max_order_size: Decimal,
    ) -> OrderRequest:
        return OrderRequest(
            token_id=trade.token_id,
            side=trade.side,
            price=trade.price,
            size=min(trade.size * self.size_multiplier, max_order_size),
            market_slug=trade.market_slug,
            condition_id=trade.condition_id,
            source_id=trade.source_key,
            reason=WALLET_FOLLOW_REASON,
        )

    async def current_wallets(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[WalletSubscription, ...]:
        return WalletSubscription.from_addresses(tuple(self.leader_wallets))

    async def on_wallet_trade(self, ctx: BotContext, trade: WalletTradeEvent) -> None:
        await ctx.broker.submit(self.order_for_trade(trade, ctx.config.max_order_size))
