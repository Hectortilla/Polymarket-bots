from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from time import time

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dedupe import SourceEventDeduper
from polybot.framework.dispatch import DispatchOutcome, DispatchSkipReason
from polybot.framework.events import FillEvent
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.runner.validation import book_skip_reason, wallet_trade_skip_reason
from polybot.framework.streams import StreamPlan


class BotRunner:
    def __init__(
        self,
        bot: BaseBot,
        ctx: BotContext,
        deduper: SourceEventDeduper | None = None,
        now_ms_fn: Callable[[], int] | None = None,
    ) -> None:
        self.bot = bot
        self.ctx = ctx
        self.deduper = deduper or SourceEventDeduper()
        self._now_ms_fn = now_ms_fn or _system_now_ms
        self.stream_plan = StreamPlan(current=())

    async def run_books(self, books: AsyncIterator[BookSnapshot]) -> None:
        await self.bot.on_start(self.ctx)
        try:
            async for book in books:
                await self.dispatch_book(book)
        finally:
            await self.bot.on_stop(self.ctx)

    async def dispatch_book(self, book: BookSnapshot) -> DispatchOutcome:
        await self.refresh_stream_plan()
        if not self.stream_plan.accepts_book(book.market_slug):
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_NOT_TRACKED)
        reason = book_skip_reason(
            book,
            now_ms=self._now_ms(),
            max_age_ms=self.ctx.config.book_max_age_ms,
        )
        if reason is not None:
            return DispatchOutcome.skipped(reason)
        await self.bot.on_book(self.ctx, book)
        return DispatchOutcome.accepted_event()

    async def dispatch_fill(self, fill: FillEvent) -> None:
        await self.bot.on_fill(self.ctx, fill)

    async def run_wallet_trades(self, trades: AsyncIterator[WalletTradeEvent]) -> None:
        await self.bot.on_start(self.ctx)
        try:
            async for trade in trades:
                await self.dispatch_wallet_trade(trade)
        finally:
            await self.bot.on_stop(self.ctx)

    async def dispatch_wallet_trade(self, trade: WalletTradeEvent) -> DispatchOutcome:
        await self.refresh_stream_plan()
        if not self.stream_plan.accepts_trade(trade.wallet, trade.market_slug):
            if any(
                trade.wallet.lower() in rule.wallet_addresses
                for rule in self.stream_plan.current
            ):
                return DispatchOutcome.skipped(DispatchSkipReason.MARKET_NOT_TRACKED)
            if any(rule.market_slugs and not rule.wallet_addresses for rule in self.stream_plan.current):
                return DispatchOutcome.skipped(DispatchSkipReason.MARKET_NOT_TRACKED)
            return DispatchOutcome.skipped(DispatchSkipReason.WALLET_NOT_TRACKED)
        reason = wallet_trade_skip_reason(
            trade,
            now_ms=self._now_ms(),
            max_age_ms=self.ctx.config.book_max_age_ms,
        )
        if reason is not None:
            return DispatchOutcome.skipped(reason)
        if not self.deduper.remember(trade.source_key):
            return DispatchOutcome.skipped(DispatchSkipReason.DUPLICATE_SOURCE_EVENT)
        await self.bot.on_wallet_trade(self.ctx, trade)
        return DispatchOutcome.accepted_event()

    async def refresh_stream_plan(self) -> StreamPlan:
        now_ms = self._now_ms()
        self.stream_plan = StreamPlan(
            current=await self.bot.current_stream_rules(self.ctx, now_ms),
            next=await self.bot.next_stream_rules(self.ctx, now_ms),
        )
        return self.stream_plan

    def _now_ms(self) -> int:
        return self._now_ms_fn()


def _system_now_ms() -> int:
    return int(time() * 1000)
