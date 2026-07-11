import asyncio
from dataclasses import replace
from decimal import Decimal

from bots.examples.example_multi_market import CrossMarketRule, ExampleMultiMarketBot
from bots.framework.context import BotContext
from bots.framework.events.books import BookLevel, BookSnapshot
from bots.polymarket.types import Market, MarketOutcome


def test_multi_market_example_trades_target_from_signal_market(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, str, Decimal, str]:
        bot = ExampleMultiMarketBot(
            rules=(
                CrossMarketRule(
                    signal_slug="btc-up",
                    target_slug="eth-down",
                    target_outcome_label="No",
                    trigger_price=Decimal("0.40"),
                    order_price=Decimal("0.52"),
                    max_size=Decimal("3"),
                ),
            )
        )

        context = replace(dummy_context, markets=_Markets())
        await bot.on_book(context, _book("btc-up", Decimal("0.39")))
        order = dummy_context.broker.submitted[0]
        return order.token_id, order.market_slug or "", order.size, order.reason or ""

    token_id, market_slug, size, reason = asyncio.run(run())

    assert token_id == "eth-no-token"
    assert market_slug == "eth-down"
    assert size == Decimal("3")
    assert reason == "cross_market_signal:btc-up"


def test_multi_market_example_declares_all_signal_and_target_markets(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, ...]:
        bot = ExampleMultiMarketBot(
            rules=(
                CrossMarketRule(
                    signal_slug="btc-up",
                    target_slug="eth-down",
                    target_outcome_label="No",
                    trigger_price=Decimal("0.40"),
                    order_price=Decimal("0.52"),
                    max_size=Decimal("3"),
                ),
            )
        )

        markets = await bot.current_markets(dummy_context, now_ms=0)
        return tuple(market.slug for market in markets)

    assert asyncio.run(run()) == ("btc-up", "eth-down")


def test_multi_market_example_ignores_unconfigured_market(
    dummy_context: BotContext,
) -> None:
    async def run() -> int:
        bot = ExampleMultiMarketBot(
            rules=(
                CrossMarketRule(
                    signal_slug="btc-up",
                    target_slug="eth-down",
                    target_outcome_label="No",
                    trigger_price=Decimal("0.40"),
                    order_price=Decimal("0.52"),
                    max_size=Decimal("3"),
                ),
            )
        )

        await bot.on_book(dummy_context, _book("sol-up", Decimal("0.20")))
        return len(dummy_context.broker.submitted)

    assert asyncio.run(run()) == 0


def _book(market_slug: str, ask_price: Decimal) -> BookSnapshot:
    return BookSnapshot(
        token_id=f"{market_slug}-token",
        bids=(),
        asks=(BookLevel(price=ask_price, size=Decimal("10")),),
        received_at_ms=10**15,
        market_slug=market_slug,
    )


class _Markets:
    async def find_by_slug(self, slug: str) -> Market | None:
        if slug != "eth-down":
            return None
        return Market(
            condition_id="condition",
            slug=slug,
            question="question",
            yes_token_id="eth-yes-token",
            no_token_id="eth-no-token",
            minimum_tick_size=Decimal("0.01"),
            minimum_order_size=Decimal("1"),
            neg_risk=False,
            fee_rate=Decimal("0"),
            outcomes=(MarketOutcome("Yes", "eth-yes-token"), MarketOutcome("No", "eth-no-token")),
        )
