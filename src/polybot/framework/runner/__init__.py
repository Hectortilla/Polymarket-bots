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
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.runner.validation import book_skip_reason, wallet_trade_skip_reason
from polybot.framework.streams import StreamPlan
from polybot.framework.wallets import normalize_wallet_address


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
        self._runtime_market_slugs: frozenset[str] = frozenset()

    def set_runtime_market_slugs(self, market_slugs: frozenset[str]) -> None:
        """Trust markets admitted by the runtime-owned tracked-market registry."""
        self._runtime_market_slugs = market_slugs

    async def run_books(self, books: AsyncIterator[BookSnapshot]) -> None:
        await self.bot.on_start(self.ctx)
        try:
            async for book in books:
                await self.dispatch_book(book)
        finally:
            await self.bot.on_stop(self.ctx)

    async def dispatch_book(self, book: BookSnapshot) -> DispatchOutcome:
        await self.refresh_stream_plan()
        if not self.stream_plan.accepts_book(book.market_slug) and (
            book.market_slug is None
            or book.market_slug not in self._runtime_market_slugs
        ):
            return DispatchOutcome.skipped(DispatchSkipReason.MARKET_NOT_TRACKED)
        reason = book_skip_reason(
            book,
            now_ms=self._now_ms(),
            max_age_ms=self.ctx.config.event_max_age_ms,
        )
        if reason is not None:
            return DispatchOutcome.skipped(reason)
        await self.bot.on_book(self.ctx, book)
        return DispatchOutcome.accepted_event()

    async def dispatch_fill(self, fill: FillEvent) -> None:
        await self.bot.on_fill(self.ctx, fill)

    async def dispatch_market_resolution(self, event: MarketResolutionEvent) -> None:
        await self.bot.on_market_resolved(self.ctx, event)

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
            return DispatchOutcome.skipped(self._wallet_trade_plan_skip_reason(trade))
        reason = wallet_trade_skip_reason(
            trade,
            now_ms=self._now_ms(),
            max_age_ms=self.ctx.config.event_max_age_ms,
        )
        if reason is not None:
            return DispatchOutcome.skipped(reason)
        if not self.deduper.remember(trade.source_key):
            return DispatchOutcome.skipped(DispatchSkipReason.DUPLICATE_SOURCE_EVENT)
        await self.bot.on_wallet_trade(self.ctx, trade)
        return DispatchOutcome.accepted_event()

    def _wallet_trade_plan_skip_reason(
        self,
        trade: WalletTradeEvent,
    ) -> DispatchSkipReason:
        if any(
            normalize_wallet_address(trade.wallet) in rule.wallet_addresses
            for rule in self.stream_plan.current
        ):
            return DispatchSkipReason.MARKET_NOT_TRACKED
        if any(
            rule.market_slugs and not rule.wallet_addresses
            for rule in self.stream_plan.current
        ):
            return DispatchSkipReason.MARKET_NOT_TRACKED
        return DispatchSkipReason.WALLET_NOT_TRACKED

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
