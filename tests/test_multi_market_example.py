import asyncio
from decimal import Decimal

from bots.examples.example_multi_market import CrossMarketRule, ExampleMultiMarketBot
from bots.framework.context import BotContext
from bots.framework.events.books import BookLevel, BookSnapshot


def test_multi_market_example_trades_target_from_signal_market(
    dummy_context: BotContext,
) -> None:
    async def run() -> tuple[str, str, Decimal, str]:
        bot = ExampleMultiMarketBot(
            rules=(
                CrossMarketRule(
                    signal_slug="btc-up",
                    target_slug="eth-down",
                    target_token_id="eth-no-token",
                    trigger_price=Decimal("0.40"),
                    order_price=Decimal("0.52"),
                    max_size=Decimal("3"),
                ),
            )
        )

        await bot.on_book(dummy_context, _book("btc-up", Decimal("0.39")))
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
                    target_token_id="eth-no-token",
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
                    target_token_id="eth-no-token",
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
