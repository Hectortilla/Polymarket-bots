import asyncio
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
from polybot.examples.example_rebound import REBOUND_ORDER_REASON, ExampleReboundBot
from polybot.polymarket.markets import Market, MarketOutcome


def test_rebound_bot_buys_after_decline_then_rise(dummy_context: BotContext) -> None:
    async def run() -> None:
        market = _market("tutorial-market", "yes-token")
        context = replace(dummy_context, markets=_Markets(market), clock=_Clock())
        bot = ExampleReboundBot(order_size=Decimal("2"))
        await bot.on_book(context, _book(Decimal("0.50")))
        await bot.on_book(context, _book(Decimal("0.45")))
        await bot.on_book(context, _book(Decimal("0.47")))

    asyncio.run(run())

    order = dummy_context.broker.submitted[0]
    assert order.side is Side.BUY
    assert order.price == Decimal("0.47")
    assert order.size == Decimal("2")
    assert order.reason == REBOUND_ORDER_REASON


def test_rebound_bot_does_not_buy_without_a_prior_decline(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        context = replace(
            dummy_context,
            markets=_Markets(_market("tutorial-market", "yes-token")),
            clock=_Clock(),
        )
        bot = ExampleReboundBot()
        await bot.on_book(context, _book(Decimal("0.45")))
        await bot.on_book(context, _book(Decimal("0.47")))

    asyncio.run(run())

    assert dummy_context.broker.submitted == []


def test_rebound_rechecks_freshness_after_market_lookup(
    dummy_context: BotContext,
) -> None:
    market = _market("tutorial-market", "yes-token")
    context = replace(
        dummy_context,
        markets=_Markets(market),
        clock=_Clock(dummy_context.config.event_max_age_ms + 2),
    )
    bot = ExampleReboundBot()

    result = asyncio.run(bot.on_book(context, _book(Decimal("0.45"))))

    assert result is DispatchSkipReason.BOOK_STALE
    assert dummy_context.broker.submitted == []


def test_rebound_gap_clears_the_pre_gap_decline_signal(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        context = replace(
            dummy_context,
            markets=_Markets(_market("tutorial-market", "yes-token")),
            clock=_Clock(),
        )
        bot = ExampleReboundBot()
        await bot.on_book(context, _book(Decimal("0.50")))
        await bot.on_book(context, _book(Decimal("0.45")))
        await bot.on_book_gap(
            context,
            BookGapEvent(
                condition_id="condition",
                observed_at_ms=1,
                reason=BookGapReason.BOOK_STREAM_GAP,
            ),
        )
        await bot.on_book(context, _book(Decimal("0.47")))

    asyncio.run(run())

    assert dummy_context.broker.submitted == []


def test_outcome_resolution_matches_only_advertised_labels() -> None:
    market = _market("tutorial-market", "yes-token")
    assert market.token_id_for_outcome("yes") == "yes-token"
    assert market.token_id_for_outcome(NO_OUTCOME) == "no-token"

    multi_market = replace(
        market,
        outcomes=(MarketOutcome("Candidate A", "candidate-a-token"),),
    )
    assert multi_market.token_id_for_outcome("candidate a") == "candidate-a-token"
    assert multi_market.token_id_for_outcome("missing") is None

    up_down = replace(
        market,
        outcomes=(
            MarketOutcome("Up", "up-token"),
            MarketOutcome("Down", "down-token"),
        ),
    )
    assert up_down.token_id_for_outcome("up") == "up-token"
    assert up_down.token_id_for_outcome(YES_OUTCOME) is None


def _book(price: Decimal) -> BookSnapshot:
    return BookSnapshot(
        token_id="yes-token",
        bids=(),
        asks=(BookLevel(price=price, size=Decimal("10")),),
        received_at_ms=1,
        market_slug="tutorial-market",
    )


class _Clock:
    def __init__(self, now_ms: int = 1) -> None:
        self._now_ms = now_ms

    def now_ms(self) -> int:
        return self._now_ms

    async def sleep(self, seconds: float) -> None:
        return None


def _market(slug: str, yes_token_id: str) -> Market:
    return Market(
        condition_id="condition",
        slug=slug,
        question="question",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
        outcomes=(
            MarketOutcome(YES_OUTCOME, yes_token_id),
            MarketOutcome(NO_OUTCOME, "no-token"),
        ),
    )


class _Markets:
    def __init__(self, market: Market) -> None:
        self.market = market

    async def find_by_slug(self, slug: str) -> Market | None:
        return self.market if slug == self.market.slug else None
