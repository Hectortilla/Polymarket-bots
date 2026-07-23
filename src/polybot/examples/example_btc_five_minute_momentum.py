from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from polybot.examples.btc_five_minute_strategy import (
    BTC_FIVE_MINUTE_SLUG_PREFIX,
    DOWN_OUTCOME,
    MOMENTUM_ENTRY_REASON,
    UP_OUTCOME,
    BookQuote,
    MomentumSettings,
    OpenPosition,
    ProbabilitySampleTransition,
    ProbabilityTrend,
    TrendMetrics,
)
from polybot.framework.activity import ActivitySeverity
from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.markets import FixedBucketTiming, market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.polymarket.markets import Market


class BtcFiveMinuteMomentumBot(BaseBot):
    """Trade short probability trends in consecutive BTC Up/Down markets.

    The signal intentionally uses only the two outcome order books. It combines
    normalized microprice momentum with an EMA trend and treats book imbalance
    only as confirmation, never as a standalone prediction.
    """

    def __init__(
        self,
        settings: MomentumSettings | None = None,
        *,
        slug_prefix: str = BTC_FIVE_MINUTE_SLUG_PREFIX,
    ) -> None:
        self.settings = settings or MomentumSettings()
        self.slug_prefix = slug_prefix
        self._market: Market | None = None
        self._up_token_id: str | None = None
        self._down_token_id: str | None = None
        self._books: dict[str, BookSnapshot] = {}
        self._trend = ProbabilityTrend(self.settings)
        self._metrics: TrendMetrics | None = None
        self._last_sample_at_ms: int | None = None
        self._position: OpenPosition | None = None
        self._cooldown_until_ms = 0

    async def current_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=0),)

    async def next_stream_rules(
        self,
        ctx: BotContext,
        now_ms: int,
    ) -> tuple[StreamRule, ...]:
        return (self._stream_rule(now_ms, bucket_offset=1),)

    async def on_book(self, ctx: BotContext, book: BookSnapshot) -> None:
        if book.market_slug is None:
            return
        current_slug = self._slug_for(book.received_at_ms, bucket_offset=0)
        if book.market_slug != current_slug:
            if self._position is not None and book.token_id == self._position.token_id:
                await self._maybe_exit(ctx, book)
            return
        if not await self._load_market(ctx, current_slug):
            return
        if book.token_id not in (self._up_token_id, self._down_token_id):
            return

        self._books[book.token_id] = book
        sampled = self._sample_probability(ctx.clock.now_ms())
        if self._position is not None:
            if book.token_id == self._position.token_id:
                await self._maybe_exit(ctx, book)
            return
        if sampled:
            await self._maybe_enter(ctx, book.received_at_ms)

    async def on_market_resolved(
        self,
        ctx: BotContext,
        event: MarketResolutionEvent,
    ) -> None:
        if (
            self._position is not None
            and event.condition_id == self._position.condition_id
        ):
            self._position = None

    async def _load_market(self, ctx: BotContext, slug: str) -> bool:
        if self._market is not None and self._market.slug == slug:
            return True
        market = await ctx.markets.find_by_slug(slug)
        if market is None:
            return False
        up_token_id = market.token_id_for_outcome(UP_OUTCOME)
        down_token_id = market.token_id_for_outcome(DOWN_OUTCOME)
        if up_token_id is None or down_token_id is None:
            return False
        self._market = market
        self._up_token_id = up_token_id
        self._down_token_id = down_token_id
        self._books = {}
        self._trend = ProbabilityTrend(self.settings)
        self._metrics = None
        self._last_sample_at_ms = None
        return True

    def _sample_probability(self, now_ms: int) -> bool:
        if self._up_token_id is None or self._down_token_id is None:
            return False
        up_book = self._books.get(self._up_token_id)
        down_book = self._books.get(self._down_token_id)
        if up_book is None or down_book is None:
            return False
        transition = ProbabilitySampleTransition.from_book_pair(
            settings=self.settings,
            trend=self._trend,
            prior_sample_at_ms=self._last_sample_at_ms,
            now_ms=now_ms,
            up_book=up_book,
            down_book=down_book,
        )
        if transition is None:
            return False
        self._last_sample_at_ms = transition.sampled_at_ms
        self._trend = transition.trend
        self._metrics = transition.metrics
        return True

    async def _maybe_enter(self, ctx: BotContext, now_ms: int) -> None:
        if (
            self._market is None
            or self._metrics is None
            or now_ms < self._cooldown_until_ms
        ):
            return
        timing = FixedBucketTiming.at(now_ms, self.settings.bucket_seconds)
        if not timing.allows_entry(
            delay_ms=self.settings.entry_delay_ms,
            cutoff_ms=self.settings.entry_cutoff_ms,
        ):
            return
        outcome = self.settings.direction(self._metrics)
        token_id = self._up_token_id if outcome == UP_OUTCOME else self._down_token_id
        if outcome is None or token_id is None:
            return
        book = self._books[token_id]
        quote = BookQuote.from_book(book)
        other_token_id = (
            self._down_token_id if outcome == UP_OUTCOME else self._up_token_id
        )
        other_quote = (
            None
            if other_token_id is None
            else BookQuote.from_book(self._books[other_token_id])
        )
        if not self.settings.entry_quote_is_safe(quote, other_quote):
            return
        size = min(
            self.settings.order_size,
            ctx.config.max_order_size,
            quote.best_ask_size,
        )
        if (
            self._market.minimum_order_size is not None
            and size < self._market.minimum_order_size
        ):
            return
        fill = await ctx.broker.submit(
            OrderRequest(
                token_id=token_id,
                side=Side.BUY,
                price=quote.best_ask,
                size=size,
                market_slug=self._market.slug,
                condition_id=self._market.condition_id,
                reason=MOMENTUM_ENTRY_REASON,
            )
        )
        if fill.filled_size <= 0:
            return
        average_price = fill.average_price or quote.best_ask
        self._position = OpenPosition(
            token_id=token_id,
            outcome=outcome,
            condition_id=self._market.condition_id,
            market_slug=self._market.slug,
            size=fill.filled_size,
            average_price=average_price,
            opened_at_ms=now_ms,
            bucket_end_ms=timing.bucket_end_ms,
        )
        await ctx.activity.emit(
            f"BTC 5m entered {outcome} at {average_price}",
            severity=ActivitySeverity.SUCCESS,
        )

    async def _maybe_exit(self, ctx: BotContext, book: BookSnapshot) -> None:
        position = self._position
        quote = BookQuote.from_book(book)
        if position is None or quote is None:
            return
        reason = self.settings.exit_reason(
            position,
            best_bid=quote.best_bid,
            now_ms=book.received_at_ms,
            current_condition_id=(
                None if self._market is None else self._market.condition_id
            ),
            metrics=self._metrics,
        )
        if reason is None:
            return
        fill = await ctx.broker.submit(
            OrderRequest(
                token_id=position.token_id,
                side=Side.SELL,
                price=quote.best_bid,
                size=position.size,
                market_slug=position.market_slug,
                condition_id=position.condition_id,
                reason=reason,
            )
        )
        remaining_size = max(Decimal("0"), position.size - fill.filled_size)
        if remaining_size > 0:
            self._position = replace(position, size=remaining_size)
            return
        self._position = None
        self._cooldown_until_ms = book.received_at_ms + self.settings.cooldown_ms
        await ctx.activity.emit(
            (
                f"BTC 5m exited {position.outcome} at "
                f"{fill.average_price or quote.best_bid} ({reason})"
            ),
            severity=ActivitySeverity.INFO,
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
            self.settings.bucket_seconds,
            bucket_offset=bucket_offset,
        )


def create() -> BtcFiveMinuteMomentumBot:
    """CLI factory for the paper-trading example."""
    return BtcFiveMinuteMomentumBot()
