"""A deliberately selective BTC five-minute breakout bot.

The strategy trades at most once in each bucket. It waits for an extreme,
accelerating leader, then buys the cheaply priced opposite outcome and realizes
the rebound with a take-profit exit. Its paper-sized request is always bounded
by the runtime's configured maximum order size.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polybot.examples.btc_five_minute_strategy import (
    BTC_FIVE_MINUTE_BUCKET_SECONDS,
    BTC_FIVE_MINUTE_SLUG_PREFIX,
)
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.markets import FixedBucketTiming, market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.polymarket.markets import Market


ENTRY_DELAY_MS = 210_000
ENTRY_CUTOFF_MS = 45_000
MOMENTUM_LOOKBACK_MS = 15_000
ENTRY_QUOTE_MAX_AGE_MS = MOMENTUM_LOOKBACK_MS
ENTRY_QUOTE_MAX_SKEW_MS = 2_000
MINIMUM_LEADER_BID = Decimal("0.85")
MAXIMUM_ENTRY_ASK = Decimal("0.16")
MINIMUM_PRICE_IMPROVEMENT = Decimal("0.04")
TAKE_PROFIT = Decimal("0.30")
PAPER_MAX_ORDER_SIZE = Decimal("51")
MAXIMUM_TRADES_PER_RUN = 2
BREAKOUT_ENTRY_REASON = "btc_5m_late_breakout"
TAKE_PROFIT_EXIT_REASON = "btc_5m_contrarian_take_profit"


@dataclass(frozen=True, slots=True)
class Quote:
    bid: Decimal
    ask: Decimal
    observed_at_ms: int

    @classmethod
    def from_book(cls, book: BookSnapshot) -> Quote | None:
        if not book.bids or not book.asks:
            return None
        return cls(
            bid=max(level.price for level in book.bids),
            ask=min(level.price for level in book.asks),
            observed_at_ms=book.received_at_ms,
        )


@dataclass(frozen=True, slots=True)
class OpenPosition:
    token_id: str
    size: Decimal
    average_price: Decimal


class WinnerTradingBot(BaseBot):
    """Buy one small, late contrarian position per BTC bucket."""

    def __init__(self, slug_prefix: str = BTC_FIVE_MINUTE_SLUG_PREFIX) -> None:
        self.slug_prefix = slug_prefix
        self._market: Market | None = None
        self._books: dict[str, Quote] = {}
        self._prior_bids: dict[str, Quote] = {}
        self._entered_condition_id: str | None = None
        self._position: OpenPosition | None = None
        self._entry_count = 0

    async def current_stream_rules(
        self, ctx: BotContext, now_ms: int
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=0),)

    async def next_stream_rules(
        self, ctx: BotContext, now_ms: int
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=1),)

    async def on_book(
        self,
        ctx: BotContext,
        book: BookSnapshot,
    ) -> DispatchSkipReason | None:
        if (
            self._entry_count >= MAXIMUM_TRADES_PER_RUN
            and self._position is None
        ):
            return
        if book.market_slug is None:
            return
        current_slug = self._slug_for(ctx.clock.now_ms(), bucket_offset=0)
        if book.market_slug != current_slug:
            return
        if not await self._load_market(ctx, current_slug):
            return
        if not ctx.is_book_current(book):
            return DispatchSkipReason.BOOK_STALE
        market = self._market
        if market is None or book.token_id not in market.token_ids:
            return
        quote = Quote.from_book(book)
        if quote is None:
            return
        self._books[book.token_id] = quote
        prior = self._prior_bids.get(book.token_id)
        if prior is None:
            self._prior_bids[book.token_id] = quote
            return
        await self._maybe_take_profit(ctx, market, book.token_id, quote)
        await self._maybe_enter(ctx, book.received_at_ms)
        if quote.observed_at_ms - prior.observed_at_ms >= MOMENTUM_LOOKBACK_MS:
            self._prior_bids[book.token_id] = quote

    async def on_market_resolved(
        self, ctx: BotContext, event: MarketResolutionEvent
    ) -> None:
        if self._market is not None and event.condition_id == self._market.condition_id:
            self._entered_condition_id = None
            self._position = None

    async def on_book_gap(self, ctx: BotContext, gap: BookGapEvent) -> None:
        market = self._market
        if market is None or not gap.affects(market.condition_id):
            return
        self._books.clear()
        self._prior_bids.clear()

    def backtest_is_quiescent(self, ctx: BotContext) -> bool:
        """Stop replaying once the intentionally capped strategy is flat."""
        return self._entry_count >= MAXIMUM_TRADES_PER_RUN and self._position is None

    async def _load_market(self, ctx: BotContext, slug: str) -> bool:
        if self._market is not None and self._market.slug == slug:
            return True
        market = await ctx.markets.find_by_slug(slug)
        if market is None or len(market.token_ids) != 2:
            return False
        self._market = market
        self._books = {}
        self._prior_bids = {}
        self._entered_condition_id = None
        self._position = None
        return True

    async def _maybe_enter(self, ctx: BotContext, now_ms: int) -> None:
        market = self._market
        if (
            market is None
            or self._entered_condition_id == market.condition_id
            or self._position is not None
            or self._entry_count >= MAXIMUM_TRADES_PER_RUN
        ):
            return
        timing = FixedBucketTiming.at(now_ms, BTC_FIVE_MINUTE_BUCKET_SECONDS)
        if not timing.allows_entry(
            delay_ms=ENTRY_DELAY_MS,
            cutoff_ms=ENTRY_CUTOFF_MS,
        ):
            return
        candidate = self._entry_candidate(market, now_ms)
        if candidate is None:
            return
        token_id, quote = candidate
        size = self._effective_order_size(ctx.config.max_order_size)
        if market.minimum_order_size is not None and size < market.minimum_order_size:
            return
        fill = await ctx.broker.submit(
            OrderRequest(
                token_id=token_id,
                side=Side.BUY,
                price=quote.ask,
                size=size,
                market_slug=market.slug,
                condition_id=market.condition_id,
                reason=BREAKOUT_ENTRY_REASON,
            )
        )
        if fill.has_execution:
            self._entered_condition_id = market.condition_id
            self._entry_count += 1
            self._position = OpenPosition(
                token_id=token_id,
                size=fill.filled_size,
                average_price=fill.execution_price,
            )

    async def _maybe_take_profit(
        self, ctx: BotContext, market: Market, token_id: str, quote: Quote
    ) -> None:
        position = self._position
        if (
            position is None
            or token_id != position.token_id
            or quote.bid < position.average_price + TAKE_PROFIT
        ):
            return
        fill = await ctx.broker.submit(
            OrderRequest(
                token_id=position.token_id,
                side=Side.SELL,
                price=quote.bid,
                size=position.size,
                market_slug=market.slug,
                condition_id=market.condition_id,
                reason=TAKE_PROFIT_EXIT_REASON,
            )
        )
        remaining = position.size - fill.filled_size
        self._position = (
            None
            if remaining <= 0
            else OpenPosition(position.token_id, remaining, position.average_price)
        )

    def _entry_candidate(
        self,
        market: Market,
        now_ms: int,
    ) -> tuple[str, Quote] | None:
        if len(self._books) != len(market.token_ids):
            return None
        if not self._quotes_are_current(market, now_ms):
            return None
        leader_token_id = max(
            market.token_ids, key=lambda value: self._books[value].bid
        )
        leader_quote = self._books[leader_token_id]
        earlier = self._prior_bids.get(leader_token_id)
        if earlier is None:
            return None
        if leader_quote.bid < MINIMUM_LEADER_BID:
            return None
        if leader_quote.bid - earlier.bid < MINIMUM_PRICE_IMPROVEMENT:
            return None
        token_id = next(
            token_id for token_id in market.token_ids if token_id != leader_token_id
        )
        quote = self._books[token_id]
        if quote.ask > MAXIMUM_ENTRY_ASK:
            return None
        return token_id, quote

    @staticmethod
    def _effective_order_size(configured_max_order_size: Decimal) -> Decimal:
        """Apply the bot's paper sizing preference within the configured risk cap."""
        return min(PAPER_MAX_ORDER_SIZE, configured_max_order_size)

    def _quotes_are_current(self, market: Market, now_ms: int) -> bool:
        quotes = tuple(self._books[token_id] for token_id in market.token_ids)
        observed_at_ms = tuple(quote.observed_at_ms for quote in quotes)
        return (
            all(
                0 <= now_ms - timestamp <= ENTRY_QUOTE_MAX_AGE_MS
                for timestamp in observed_at_ms
            )
            and max(observed_at_ms) - min(observed_at_ms) <= ENTRY_QUOTE_MAX_SKEW_MS
        )

    def _stream_rule(self, now_ms: int, *, bucket_offset: int) -> StreamRule:
        return StreamRule(
            StreamRelation.INDEPENDENT,
            (self._slug_for(now_ms, bucket_offset=bucket_offset),),
        )

    def _slug_for(self, now_ms: int, *, bucket_offset: int) -> str:
        return market_bucket_slug(
            self.slug_prefix,
            now_ms,
            BTC_FIVE_MINUTE_BUCKET_SECONDS,
            bucket_offset=bucket_offset,
        )


def create() -> WinnerTradingBot:
    """CLI factory for the BTC five-minute contrarian strategy."""
    return WinnerTradingBot()
