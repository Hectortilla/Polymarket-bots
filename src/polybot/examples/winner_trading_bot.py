"""Selective leader-following strategy for five-minute BTC markets.

The bot waits until one outcome has established a strong late probability
lead, buys that outcome, and holds through resolution.  It deliberately keeps
one position at a time so a bad market cannot compound across simultaneous
buckets.

All inputs are normalized framework contracts.  In particular, the strategy
does not rely on SDK payloads or on a particular token-ID ordering.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal

from polybot.framework.base import BaseBot
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import OrderRequest, Side
from polybot.framework.events.books import BookGapEvent, BookSnapshot
from polybot.framework.events.resolutions import MarketResolutionEvent
from polybot.framework.markets import FixedBucketTiming, market_bucket_slug
from polybot.framework.streams import StreamRelation, StreamRule
from polybot.polymarket.markets import Market


BTC_FIVE_MINUTE_SLUG_PREFIX = "btc-updown-5m"
BUCKET_SECONDS = 300

# The signal and trade window are intentionally late: the leader must have
# repriced materially before capital is committed.  The final 45 seconds are
# left for the venue to resolve the market and for the paper broker to settle.
ENTRY_DELAY_MS = 210_000
ENTRY_CUTOFF_MS = 45_000
EARLY_ENTRY_MAX_ELAPSED_MS = 212_000
EARLY_ENTRY_MIN_ELAPSED_MS = 211_000
LATE_CONFIRMATION_DELAY_MS = 246_000
ENTRY_QUOTE_MAX_AGE_MS = 5_000
ENTRY_QUOTE_MAX_SKEW_MS = 2_000
RECENT_STABILITY_WINDOW_MS = 2_000
RECENT_BID_HISTORY_WINDOW_MS = 20_000
MAX_RECOVERY_AGE_MS = 5_000
LEADER_BID_THRESHOLD = Decimal("0.97")
MINIMUM_STABLE_LEADER_BID = Decimal("0.96")
LATE_LEADER_BID_THRESHOLD = Decimal("0.99")
LATE_MINIMUM_STABLE_LEADER_BID = Decimal("0.96")
LATE_CLEAR_REPRICING_BID = Decimal("0.96")
LATE_RECOVERY_REPRICING_BID = Decimal("0.90")
RECOVERY_MINIMUM_BID = Decimal("0.94")
MAXIMUM_ENTRY_SPREAD = Decimal("0.04")
MAXIMUM_OPPOSITE_ASK = Decimal("0.20")
EARLY_MAXIMUM_LEADER_ASK = Decimal("0.98")
EARLY_MINIMUM_LEADER_ASK_SIZE = Decimal("220")
MAXIMUM_STOP_LOSS = Decimal("0.05")

# This is a deliberate paper-example override of the framework's conservative
# default.  The late entry and one-position limit bound exposure, while the
# actual paper broker still owns fill validation and portfolio accounting.
PAPER_MAX_ORDER_SIZE = Decimal("240")
RECOVERED_MAX_ORDER_SIZE = Decimal("240")

LEADER_ENTRY_REASON = "btc_5m_leader_momentum_entry"


@dataclass(frozen=True, slots=True)
class Quote:
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    observed_at_ms: int

    @classmethod
    def from_book(cls, book: BookSnapshot) -> Quote | None:
        if not book.bids or not book.asks:
            return None
        bid = max(book.bids, key=lambda level: level.price)
        ask = min(book.asks, key=lambda level: level.price)
        if bid.price >= ask.price or bid.size <= 0 or ask.size <= 0:
            return None
        return cls(
            bid=bid.price,
            ask=ask.price,
            bid_size=bid.size,
            ask_size=ask.size,
            observed_at_ms=book.received_at_ms,
        )


@dataclass(frozen=True, slots=True)
class OpenPosition:
    token_id: str
    condition_id: str
    market_slug: str
    size: Decimal
    average_price: Decimal


class WinnerTradingBot(BaseBot):
    """Follow a strong, confirmed BTC outcome leader with bounded risk."""

    def __init__(
        self,
        slug_prefix: str = BTC_FIVE_MINUTE_SLUG_PREFIX,
        bucket_seconds: int = BUCKET_SECONDS,
    ) -> None:
        self.slug_prefix = slug_prefix
        self.bucket_seconds = bucket_seconds
        self._markets: dict[str, Market] = {}
        self._quotes: dict[str, dict[str, Quote]] = {}
        self._bid_history: dict[str, dict[str, deque[tuple[int, Decimal]]]] = {}
        self._entered_conditions: set[str] = set()
        self._position: OpenPosition | None = None

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

    async def on_book(
        self,
        ctx: BotContext,
        book: BookSnapshot,
    ) -> DispatchSkipReason | None:
        if book.market_slug is None:
            return
        if not ctx.is_book_current(book):
            return DispatchSkipReason.BOOK_STALE

        market = await self._market_for(ctx, book.market_slug)
        if market is None or book.token_id not in market.token_ids:
            return
        quote = Quote.from_book(book)
        if quote is None:
            return

        condition_quotes = self._quotes.setdefault(market.condition_id, {})
        condition_quotes[book.token_id] = quote
        bid_history = self._bid_history.setdefault(market.condition_id, {}).setdefault(
            book.token_id,
            deque(),
        )
        bid_history.append((quote.observed_at_ms, quote.bid))
        while bid_history and bid_history[0][0] < (
            quote.observed_at_ms - RECENT_BID_HISTORY_WINDOW_MS
        ):
            bid_history.popleft()

        current_slug = self._slug_for(ctx.clock.now_ms(), bucket_offset=0)
        if market.slug != current_slug or book.token_id not in market.token_ids:
            return
        now_ms = ctx.clock.now_ms()
        await self._maybe_exit(ctx, market, book.token_id, quote)
        if self._position is None:
            await self._maybe_enter(ctx, market, now_ms)

    async def on_market_resolved(
        self,
        ctx: BotContext,
        event: MarketResolutionEvent,
    ) -> None:
        self._quotes.pop(event.condition_id, None)
        self._bid_history.pop(event.condition_id, None)
        self._entered_conditions.add(event.condition_id)
        if (
            self._position is not None
            and self._position.condition_id == event.condition_id
        ):
            self._position = None

    async def on_book_gap(self, ctx: BotContext, gap: BookGapEvent) -> None:
        affected_conditions = {
            condition_id
            for condition_id in self._quotes
            if gap.affects(condition_id)
        }
        for condition_id in affected_conditions:
            self._quotes.pop(condition_id, None)
            self._bid_history.pop(condition_id, None)
        if self._position is not None and gap.affects(self._position.condition_id):
            # Keep the position for portfolio/settlement accounting, but do not
            # manufacture an exit price from a pre-gap book.
            self._quotes.pop(self._position.condition_id, None)

    async def _market_for(self, ctx: BotContext, slug: str) -> Market | None:
        market = self._markets.get(slug)
        if market is not None:
            return market
        market = await ctx.markets.find_by_slug(slug)
        if market is None or len(market.token_ids) != 2:
            return None
        self._markets[slug] = market
        return market

    async def _maybe_enter(
        self,
        ctx: BotContext,
        market: Market,
        now_ms: int,
    ) -> None:
        if (
            self._position is not None
            or market.condition_id in self._entered_conditions
        ):
            return
        timing = FixedBucketTiming.at(now_ms, self.bucket_seconds)
        if not timing.allows_entry(
            delay_ms=ENTRY_DELAY_MS,
            cutoff_ms=ENTRY_CUTOFF_MS,
        ):
            return
        quotes = self._quotes.get(market.condition_id)
        if quotes is None or len(quotes) != 2:
            return
        if not self._quotes_are_current(market, quotes, now_ms):
            return

        leader_token_id = max(
            market.token_ids,
            key=lambda token_id: quotes[token_id].bid,
        )
        opposite_token_id = next(
            token_id for token_id in market.token_ids if token_id != leader_token_id
        )
        leader = quotes[leader_token_id]
        opposite = quotes[opposite_token_id]
        late_confirmation = timing.elapsed_ms >= LATE_CONFIRMATION_DELAY_MS
        recovery_age_ms = self._leader_recovery_age_ms(
            market.condition_id,
            leader_token_id,
            now_ms,
        )
        late_recovery = (
            late_confirmation
            and leader.bid < Decimal("0.98")
            and recovery_age_ms is not None
        )
        minimum_leader_bid = (
            LATE_LEADER_BID_THRESHOLD
            if late_confirmation
            else LEADER_BID_THRESHOLD
        )
        minimum_stable_leader_bid = (
            LATE_MINIMUM_STABLE_LEADER_BID
            if late_confirmation
            else MINIMUM_STABLE_LEADER_BID
        )
        if (
            (leader.bid < minimum_leader_bid and not late_recovery)
            or leader.ask - leader.bid > MAXIMUM_ENTRY_SPREAD
            or opposite.ask > MAXIMUM_OPPOSITE_ASK
            or not self._leader_was_stable(
                market.condition_id,
                leader_token_id,
                now_ms,
                minimum_bid=minimum_stable_leader_bid,
            )
            or (
                late_confirmation
                and not self._leader_is_at_recent_high(
                    market.condition_id,
                    leader_token_id,
                    now_ms,
                    current_bid=leader.bid,
                )
            )
            or (
                late_confirmation
                and not self._late_entry_has_clear_repricing(
                    market.condition_id,
                    leader_token_id,
                    now_ms,
                )
            )
            or (not late_confirmation and leader.ask > EARLY_MAXIMUM_LEADER_ASK)
            or (
                not late_confirmation
                and leader.ask_size < EARLY_MINIMUM_LEADER_ASK_SIZE
            )
            or (
                not late_confirmation
                and (
                    timing.elapsed_ms < EARLY_ENTRY_MIN_ELAPSED_MS
                    or timing.elapsed_ms >= EARLY_ENTRY_MAX_ELAPSED_MS
                )
            )
        ):
            return

        if recovery_age_ms is not None and recovery_age_ms > MAX_RECOVERY_AGE_MS:
            return
        # A recent sharp recovery is still tradable, but it gets a smaller
        # request because a reversal can exhaust top-of-book depth quickly.
        size_cap = (
            RECOVERED_MAX_ORDER_SIZE
            if recovery_age_ms is not None
            else PAPER_MAX_ORDER_SIZE
        )
        # The broker remains the sole authority for available depth, slippage,
        # and fee calculation; partial fills are handled below.
        size = min(size_cap, leader.ask_size)
        if market.minimum_order_size is not None and size < market.minimum_order_size:
            return
        fill = await ctx.broker.submit(
            OrderRequest(
                token_id=leader_token_id,
                side=Side.BUY,
                price=leader.ask,
                size=size,
                market_slug=market.slug,
                condition_id=market.condition_id,
                reason=LEADER_ENTRY_REASON,
            )
        )
        if not fill.has_execution:
            return
        self._entered_conditions.add(market.condition_id)
        self._position = OpenPosition(
            token_id=leader_token_id,
            condition_id=market.condition_id,
            market_slug=market.slug,
            size=fill.filled_size,
            average_price=fill.execution_price,
        )

    def _leader_was_stable(
        self,
        condition_id: str,
        token_id: str,
        now_ms: int,
        *,
        minimum_bid: Decimal,
    ) -> bool:
        history = self._bid_history.get(condition_id, {}).get(token_id)
        if not history:
            return False
        recent_bids = self._recent_bids(
            history,
            now_ms,
            RECENT_STABILITY_WINDOW_MS,
        )
        return bool(recent_bids) and min(recent_bids) >= minimum_bid

    def _leader_recovery_age_ms(
        self,
        condition_id: str,
        token_id: str,
        now_ms: int,
    ) -> int | None:
        history = self._bid_history.get(condition_id, {}).get(token_id)
        if not history:
            return None
        recovery_times = [
            observed_at_ms
            for observed_at_ms, bid in history
            if observed_at_ms >= now_ms - RECENT_BID_HISTORY_WINDOW_MS
            and bid < RECOVERY_MINIMUM_BID
        ]
        if not recovery_times:
            return None
        return now_ms - max(recovery_times)

    def _leader_is_at_recent_high(
        self,
        condition_id: str,
        token_id: str,
        now_ms: int,
        *,
        current_bid: Decimal,
    ) -> bool:
        history = self._bid_history.get(condition_id, {}).get(token_id)
        if not history:
            return False
        recent_bids = self._recent_bids(
            history,
            now_ms,
            RECENT_BID_HISTORY_WINDOW_MS,
        )
        return bool(recent_bids) and current_bid >= max(recent_bids)

    def _late_entry_has_clear_repricing(
        self,
        condition_id: str,
        token_id: str,
        now_ms: int,
    ) -> bool:
        history = self._bid_history.get(condition_id, {}).get(token_id)
        if not history:
            return False
        recent_bids = self._recent_bids(
            history,
            now_ms,
            RECENT_BID_HISTORY_WINDOW_MS,
        )
        if not recent_bids:
            return False
        recent_low = min(recent_bids)
        return (
            recent_low >= LATE_CLEAR_REPRICING_BID
            or recent_low <= LATE_RECOVERY_REPRICING_BID
        )

    @staticmethod
    def _recent_bids(
        history: deque[tuple[int, Decimal]],
        now_ms: int,
        window_ms: int,
    ) -> list[Decimal]:
        cutoff_ms = now_ms - window_ms
        return [
            bid for observed_at_ms, bid in history if observed_at_ms >= cutoff_ms
        ]

    async def _maybe_exit(
        self,
        ctx: BotContext,
        market: Market,
        token_id: str,
        quote: Quote,
    ) -> None:
        position = self._position
        if (
            position is None
            or position.condition_id != market.condition_id
            or position.token_id != token_id
            or quote.bid > position.average_price - MAXIMUM_STOP_LOSS
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
                reason="btc_5m_leader_momentum_stop",
            )
        )
        remaining = position.size - fill.filled_size
        self._position = (
            None
            if remaining <= 0
            else OpenPosition(
                token_id=position.token_id,
                condition_id=position.condition_id,
                market_slug=position.market_slug,
                size=remaining,
                average_price=position.average_price,
            )
        )

    def _quotes_are_current(
        self,
        market: Market,
        quotes: dict[str, Quote],
        now_ms: int,
    ) -> bool:
        observed = tuple(
            quotes[token_id].observed_at_ms for token_id in market.token_ids
        )
        return (
            all(
                0 <= now_ms - timestamp <= ENTRY_QUOTE_MAX_AGE_MS
                for timestamp in observed
            )
            and max(observed) - min(observed) <= ENTRY_QUOTE_MAX_SKEW_MS
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
            self.bucket_seconds,
            bucket_offset=bucket_offset,
        )


def create() -> WinnerTradingBot:
    """CLI factory for the BTC five-minute leader strategy."""
    return WinnerTradingBot()
