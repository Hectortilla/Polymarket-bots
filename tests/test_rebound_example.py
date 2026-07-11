import asyncio
from dataclasses import replace
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.examples.example_rebound import ExampleReboundBot
from polybot.polymarket.types import Market, MarketOutcome
from polybot.framework.outcomes import resolve_outcome_token


def test_rebound_bot_buys_after_decline_then_rise(dummy_context: BotContext) -> None:
    async def run() -> None:
        market = _market("tutorial-market", "yes-token")
        context = replace(dummy_context, markets=_Markets(market))
        bot = ExampleReboundBot(order_size=Decimal("2"))
        await bot.on_book(context, _book(Decimal("0.50")))
        await bot.on_book(context, _book(Decimal("0.45")))
        await bot.on_book(context, _book(Decimal("0.47")))

    asyncio.run(run())

    order = dummy_context.broker.submitted[0]
    assert order.side.value == "BUY"
    assert order.price == Decimal("0.47")
    assert order.size == Decimal("2")
    assert order.reason == "price_rebound"


def test_rebound_bot_does_not_buy_without_a_prior_decline(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        context = replace(dummy_context, markets=_Markets(_market("tutorial-market", "yes-token")))
        bot = ExampleReboundBot()
        await bot.on_book(context, _book(Decimal("0.45")))
        await bot.on_book(context, _book(Decimal("0.47")))

    asyncio.run(run())

    assert dummy_context.broker.submitted == []


def test_outcome_resolution_supports_binary_and_arbitrary_labels() -> None:
    market = _market("tutorial-market", "yes-token")
    assert resolve_outcome_token(market, "yes") == "yes-token"
    assert resolve_outcome_token(market, "No") == "no-token"

    multi_market = replace(
        market,
        outcomes=(MarketOutcome("Candidate A", "candidate-a-token"),),
    )
    assert resolve_outcome_token(multi_market, "candidate a") == "candidate-a-token"
    assert resolve_outcome_token(multi_market, "missing") is None


def _book(price: Decimal) -> BookSnapshot:
    return BookSnapshot(
        token_id="yes-token",
        bids=(),
        asks=(BookLevel(price=price, size=Decimal("10")),),
        received_at_ms=1,
        market_slug="tutorial-market",
    )


def _market(slug: str, yes_token_id: str) -> Market:
    return Market(
        condition_id="condition",
        slug=slug,
        question="question",
        yes_token_id=yes_token_id,
        no_token_id="no-token",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal("0"),
        outcomes=(MarketOutcome("Yes", yes_token_id), MarketOutcome("No", "no-token")),
    )


class _Markets:
    def __init__(self, market: Market) -> None:
        self.market = market

    async def find_by_slug(self, slug: str) -> Market | None:
        return self.market if slug == self.market.slug else None
