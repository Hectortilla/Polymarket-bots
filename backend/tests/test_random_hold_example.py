import asyncio
import random
from dataclasses import replace
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import Side
from polybot.framework.events.books import (
    BookGapEvent,
    BookGapReason,
    BookLevel,
    BookSnapshot,
)
from polybot.framework.outcomes import NO_OUTCOME, YES_OUTCOME
from polybot.polymarket.markets import Market, MarketOutcome
from polybot.examples.example_random_hold import (
    RANDOM_HOLD_BUY_REASON,
    RANDOM_HOLD_SELL_REASON,
    ExampleRandomHoldBot,
)


def test_random_hold_bot_buys_holds_then_sells_and_starts_again(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        clock = _Clock()
        context = replace(
            dummy_context,
            markets=_Markets(),
            clock=clock,
            rng=random.Random(1),
        )
        bot = ExampleRandomHoldBot(
            hold_seconds=5,
            order_size=Decimal("2"),
        )

        await bot.on_book(context, _book("yes-token", asks=("0.40",), bids=("0.38",)))
        await bot.on_book(context, _book("yes-token", asks=("0.41",), bids=("0.39",)))
        clock.current_ms = 5_001
        await bot.on_book(context, _book("yes-token", asks=("0.42",), bids=("0.40",)))
        await bot.on_book(context, _book("yes-token", asks=("0.45",), bids=("0.43",)))

    asyncio.run(run())

    assert [order.side for order in dummy_context.broker.submitted] == [
        Side.BUY,
        Side.SELL,
        Side.BUY,
    ]
    assert dummy_context.broker.submitted[0].reason == RANDOM_HOLD_BUY_REASON
    assert dummy_context.broker.submitted[1].reason == RANDOM_HOLD_SELL_REASON
    assert dummy_context.broker.submitted[1].price == Decimal("0.40")


def test_random_hold_rechecks_freshness_after_market_lookup(
    dummy_context: BotContext,
) -> None:
    clock = _Clock()
    clock.current_ms = dummy_context.config.event_max_age_ms + 2
    context = replace(dummy_context, markets=_Markets(), clock=clock)
    bot = ExampleRandomHoldBot(rng=random.Random(1))

    result = asyncio.run(
        bot.on_book(
            context,
            _book("yes-token", asks=("0.40",), bids=("0.38",)),
        )
    )

    assert result is DispatchSkipReason.BOOK_STALE
    assert dummy_context.broker.submitted == []


def test_random_hold_gap_preserves_the_open_position_identity(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        clock = _Clock()
        context = replace(dummy_context, markets=_Markets(), clock=clock)
        bot = ExampleRandomHoldBot(
            hold_seconds=5,
            rng=_SequenceRng((0, 1)),
        )
        await bot.on_book(
            context,
            _book("yes-token", asks=("0.40",), bids=("0.38",)),
        )
        await bot.on_book_gap(
            context,
            BookGapEvent(
                condition_id="condition",
                observed_at_ms=2,
                reason=BookGapReason.BOOK_STREAM_GAP,
            ),
        )
        clock.current_ms = 5_001
        await bot.on_book(
            context,
            _book("no-token", asks=("0.60",), bids=("0.58",)),
        )
        await bot.on_book(
            context,
            _book("yes-token", asks=("0.42",), bids=("0.40",)),
        )

    asyncio.run(run())

    assert [order.token_id for order in dummy_context.broker.submitted] == [
        "yes-token",
        "yes-token",
    ]
    assert [order.side for order in dummy_context.broker.submitted] == [
        Side.BUY,
        Side.SELL,
    ]


def _book(token_id: str, *, asks: tuple[str, ...], bids: tuple[str, ...]) -> BookSnapshot:
    return BookSnapshot(
        token_id=token_id,
        asks=tuple(BookLevel(Decimal(price), Decimal("10")) for price in asks),
        bids=tuple(BookLevel(Decimal(price), Decimal("10")) for price in bids),
        received_at_ms=1,
        market_slug="tutorial-market",
    )


class _Markets:
    async def find_by_slug(self, slug: str) -> Market | None:
        return Market(
            condition_id="condition",
            slug=slug,
            question="question",
            minimum_tick_size=Decimal("0.01"),
            minimum_order_size=Decimal("1"),
            neg_risk=False,
            fee_rate=Decimal("0"),
            outcomes=(
                MarketOutcome(YES_OUTCOME, "yes-token"),
                MarketOutcome(NO_OUTCOME, "no-token"),
            ),
        )


class _Clock:
    def __init__(self) -> None:
        self.current_ms = 1

    def now_ms(self) -> int:
        return self.current_ms

    async def sleep(self, seconds: float) -> None:
        self.current_ms += round(seconds * 1000)


class _SequenceRng:
    def __init__(self, indexes: tuple[int, ...]) -> None:
        self._indexes = iter(indexes)

    def randrange(self, stop: int) -> int:
        index = next(self._indexes)
        assert index < stop
        return index
