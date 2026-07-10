from __future__ import annotations

from collections.abc import AsyncIterator
from time import time

from bots.framework.base import BaseBot
from bots.framework.context import BotContext
from bots.framework.dedupe import SourceEventDeduper
from bots.framework.events import BookSnapshot, FillEvent, WalletTradeEvent
from bots.framework.markets import MarketPlan


class BotRunner:
    def __init__(
        self,
        bot: BaseBot,
        ctx: BotContext,
        deduper: SourceEventDeduper | None = None,
    ) -> None:
        self.bot = bot
        self.ctx = ctx
        self.deduper = deduper or SourceEventDeduper()
        self.market_plan = MarketPlan(current=())

    async def run_books(self, books: AsyncIterator[BookSnapshot]) -> None:
        await self.bot.on_start(self.ctx)
        try:
            async for book in books:
                await self.dispatch_book(book)
        finally:
            await self.bot.on_stop(self.ctx)

    async def dispatch_book(self, book: BookSnapshot) -> bool:
        await self.refresh_markets()
        if not self._accept_book(book):
            return False
        await self.bot.on_book(self.ctx, book)
        return True

    async def dispatch_fill(self, fill: FillEvent) -> None:
        await self.bot.on_fill(self.ctx, fill)

    async def run_wallet_trades(
        self,
        trades: AsyncIterator[WalletTradeEvent],
    ) -> None:
        await self.bot.on_start(self.ctx)
        try:
            async for trade in trades:
                await self.dispatch_wallet_trade(trade)
        finally:
            await self.bot.on_stop(self.ctx)

    async def dispatch_wallet_trade(self, trade: WalletTradeEvent) -> bool:
        await self.refresh_markets()
        if not self._accept_market_slug(trade.market_slug):
            return False
        if not self._accept_wallet_trade(trade):
            return False
        if not self.deduper.remember(trade.source_id):
            return False

        await self.bot.on_wallet_trade(self.ctx, trade)
        return True

    async def refresh_markets(self) -> MarketPlan:
        now_ms = self._now_ms()
        self.market_plan = MarketPlan(
            current=await self.bot.current_markets(self.ctx, now_ms),
            next=await self.bot.next_markets(self.ctx, now_ms),
        )
        return self.market_plan

    def _accept_book(self, book: BookSnapshot) -> bool:
        return (
            self._accept_market_slug(book.market_slug)
            and book.is_fresh(self._now_ms(), self.ctx.config.book_max_age_ms)
            and book.has_valid_levels()
        )

    def _accept_market_slug(self, market_slug: str | None) -> bool:
        active_slugs = self.market_plan.active_slugs
        if not active_slugs:
            return True
        if market_slug is None:
            return False
        return market_slug in active_slugs

    def _accept_wallet_trade(self, trade: WalletTradeEvent) -> bool:
        if not trade.source_id:
            return False
        return trade.observed_at_ms - trade.trade_timestamp_ms <= self.ctx.config.book_max_age_ms

    @staticmethod
    def _now_ms() -> int:
        return int(time() * 1000)
