from __future__ import annotations

from decimal import Decimal

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.events import OrderRequest, Side
from bots.framework.events.books import BookSnapshot

PRICE_TRIGGER = Decimal("0.45")


class ExamplePriceWatcher(BaseBot):
    def __init__(self, yes_token_id: str) -> None:
        self.yes_token_id = yes_token_id

    def order_for_book(
        self,
        book: BookSnapshot,
        max_order_size: Decimal,
    ) -> OrderRequest | None:
        if book.token_id != self.yes_token_id or not book.asks:
            return None
        best_ask = min(book.asks, key=lambda level: level.price)
        if best_ask.price > PRICE_TRIGGER:
            return None
        return OrderRequest(
            token_id=self.yes_token_id,
            side=Side.BUY,
            price=best_ask.price,
            size=min(best_ask.size, max_order_size),
        )

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        order = self.order_for_book(book, ctx.config.max_order_size)
        if order is not None:
            await ctx.broker.submit(order)
