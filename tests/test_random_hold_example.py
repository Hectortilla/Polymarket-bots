import asyncio
import random
from dataclasses import replace
from decimal import Decimal

from polybot.framework.context import BotContext
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.polymarket.types import Market, MarketOutcome
from polybot.examples.example_random_hold import ExampleRandomHoldBot


def test_random_hold_bot_buys_holds_then_sells_and_starts_again(
    dummy_context: BotContext,
) -> None:
    async def run() -> None:
        clock = [0.0]
        context = replace(dummy_context, markets=_Markets())
        bot = ExampleRandomHoldBot(
            hold_seconds=5,
            order_size=Decimal("2"),
            rng=random.Random(1),
            monotonic_fn=lambda: clock[0],
        )

        await bot.on_book(context, _book("yes-token", asks=("0.40",), bids=("0.38",)))
        await bot.on_book(context, _book("yes-token", asks=("0.41",), bids=("0.39",)))
        clock[0] = 5
        await bot.on_book(context, _book("yes-token", asks=("0.42",), bids=("0.40",)))
        await bot.on_book(context, _book("yes-token", asks=("0.45",), bids=("0.43",)))

    asyncio.run(run())

    assert [order.side.value for order in dummy_context.broker.submitted] == ["BUY", "SELL", "BUY"]
    assert dummy_context.broker.submitted[0].reason == "random_hold_buy"
    assert dummy_context.broker.submitted[1].reason == "random_hold_sell"
    assert dummy_context.broker.submitted[1].price == Decimal("0.40")


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
            yes_token_id="yes-token",
            no_token_id="no-token",
            minimum_tick_size=Decimal("0.01"),
            minimum_order_size=Decimal("1"),
            neg_risk=False,
            fee_rate=Decimal("0"),
            outcomes=(
                MarketOutcome("Yes", "yes-token"),
                MarketOutcome("No", "no-token"),
            ),
        )
