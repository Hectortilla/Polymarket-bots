from __future__ import annotations

from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import BookSnapshot, OrderRequest, Side


class ExamplePriceWatcher(BaseBot):
    def __init__(self, yes_token_id: str) -> None:
        self.yes_token_id = yes_token_id

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.token_id != self.yes_token_id or not book.asks:
            return

        best_ask = book.asks[0]
        if best_ask.price <= Decimal("0.45"):
            await ctx.broker.submit(
                OrderRequest(
                    token_id=self.yes_token_id,
                    side=Side.BUY,
                    price=best_ask.price,
                    size=min(best_ask.size, ctx.config.max_order_size),
                )
            )
