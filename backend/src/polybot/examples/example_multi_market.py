from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.streams import StreamRelation, StreamRule


@dataclass(frozen=True, slots=True)
class CrossMarketRule:
    signal_slug: str
    target_slug: str
    target_outcome_label: str
    trigger_price: Decimal
    order_price: Decimal
    max_size: Decimal


class ExampleMultiMarketBot(BaseBot):
    def __init__(self, rules: tuple[CrossMarketRule, ...]) -> None:
        self.rules = rules
        self._target_token_ids: dict[str, str | None] = {}

    def orders_for_book(
        self,
        book: BookSnapshot,
        max_order_size: Decimal,
    ) -> tuple[OrderRequest, ...]:
        if book.market_slug is None or not book.asks:
            return ()
        best_ask = min(book.asks, key=lambda level: level.price)
        orders: list[OrderRequest] = []
        for rule in self.rules:
            if (
                book.market_slug != rule.signal_slug
                or best_ask.price > rule.trigger_price
            ):
                continue
            order = self._order_for_rule(
                rule,
                self._target_token_ids.get(rule.target_slug),
                max_order_size,
            )
            if order is not None:
                orders.append(order)
        return tuple(orders)

    @staticmethod
    def _order_for_rule(
        rule: CrossMarketRule,
        target_token_id: str | None,
        max_order_size: Decimal,
    ) -> OrderRequest | None:
        if target_token_id is None:
            return None
        return OrderRequest(
            token_id=target_token_id,
            side=Side.BUY,
            price=rule.order_price,
            size=min(rule.max_size, max_order_size),
            market_slug=rule.target_slug,
            reason=f"cross_market_signal:{rule.signal_slug}",
        )

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        slugs = {rule.signal_slug for rule in self.rules}
        slugs.update(rule.target_slug for rule in self.rules)
        return (StreamRule(StreamRelation.INDEPENDENT, tuple(sorted(slugs))),)

    async def on_book(
        self,
        ctx: BotContext,
        book: BookSnapshot,
    ) -> DispatchSkipReason | None:
        if book.market_slug is None:
            return
        for rule in self.rules:
            if rule.target_slug not in self._target_token_ids:
                market = await ctx.markets.find_by_slug(rule.target_slug)
                self._target_token_ids[rule.target_slug] = (
                    None
                    if market is None
                    else market.token_id_for_outcome(rule.target_outcome_label)
                )
        if not ctx.is_book_current(book):
            return DispatchSkipReason.BOOK_STALE
        for order in self.orders_for_book(book, ctx.config.max_order_size):
            if not ctx.is_book_current(book):
                return DispatchSkipReason.BOOK_STALE
            await ctx.broker.submit(order)
        return None
