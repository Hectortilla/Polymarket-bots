"""Random graph signals use run randomness and real paper fill accounting."""

import asyncio
import random
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from api.catalog.graphs.examples import GRAPH_EXAMPLES, random_example
from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.values import GraphPort
from api.catalog.node_based.evaluator import GraphEvaluator
from polybot.execution.paper import PaperBroker
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.execution.paper.portfolio_reader import PaperPortfolioReader
from polybot.framework.base import BaseBot
from polybot.framework.events import FillEvent, FillRejectReason, OrderStatus, Side
from polybot.framework.events.books import BookLevel, BookSnapshot
from polybot.polymarket.markets import Market, MarketOutcome


def random_output(result):
    return next(node for node in result.nodes if node.node_id == "random").outputs[
        GraphPort.VALUE
    ]


def test_random_example_is_a_catalog_starting_point():
    assert random_example() in GRAPH_EXAMPLES


def test_random_draws_are_seeded_shared_and_cooldown_gated(dummy_context):
    async def run():
        ctx = replace(dummy_context, rng=random.Random(1), clock=Mock())
        expected = random.Random(1)
        evaluator = GraphEvaluator(random_example().graph, preview=True)
        for index, now in enumerate((1000, 1000, 6000, 11000, 16000)):
            ctx.clock.now_ms.return_value = now
            book = BookSnapshot(
                "token",
                (BookLevel(Decimal("0.4"), Decimal(10)),),
                (BookLevel(Decimal("0.5"), Decimal(10)),),
                now,
            )
            result = await evaluator.evaluate_and_execute(
                BaseBot.on_book.__name__, ctx, book
            )
            value = random_output(result)
            if index == 1:
                assert value.reason is GraphReason.DISABLED
                assert value.value is None
            else:
                assert Decimal(value.value) == Decimal(str(expected.random()))
                assert Decimal(0) <= Decimal(value.value) < Decimal(1)
        assert ctx.rng.getstate() == expected.getstate()

    asyncio.run(run())


@pytest.mark.parametrize("depth", [Decimal(100), Decimal(1)])
def test_random_template_buys_and_sells_actual_paper_holdings(dummy_context, depth):
    async def run():
        clock = Mock()
        clock.sleep = AsyncMock()
        config = dummy_context.config.with_overrides(
            paper_latency_ms=0, paper_latency_jitter_ms=0
        )
        books = AsyncMock()
        market = Market(
            condition_id="condition",
            slug="market",
            question="Debug market",
            minimum_tick_size=Decimal("0.01"),
            minimum_order_size=Decimal(1),
            neg_risk=False,
            fee_rate=Decimal(0),
            outcomes=(MarketOutcome("Up", "token"), MarketOutcome("Down", "other")),
            active=True,
            closed=False,
            order_book_enabled=True,
            accepting_orders=True,
        )
        markets = Mock(find_by_slug=AsyncMock(return_value=market))
        broker = PaperBroker(config, books, markets, clock=clock)
        ctx = replace(
            dummy_context,
            config=config,
            broker=broker,
            books=books,
            clock=clock,
            portfolio=PaperPortfolioReader(broker.portfolio),
            rng=random.Random(1),
        )
        evaluator = GraphEvaluator(random_example().graph)
        fills = []
        for now in (1000, 1001, 6000, 11000, 16000):
            clock.now_ms.return_value = now
            book = BookSnapshot(
                "token",
                (BookLevel(Decimal("0.4"), depth),),
                (BookLevel(Decimal("0.5"), depth),),
                now,
                market_slug=market.slug,
                condition_id=market.condition_id,
            )
            ctx.books.latest = AsyncMock(return_value=book)
            result = await evaluator.evaluate_and_execute(
                BaseBot.on_book.__name__, ctx, book
            )
            fills.extend(
                action.fill
                for action in result.action_results
                if action.fill is not None
            )
        assert [fill.side for fill in fills] == [Side.BUY, Side.SELL]
        assert fills[0].status is (
            OrderStatus.FILLED if depth == 100 else OrderStatus.PARTIAL
        )
        assert fills[1].filled_size == fills[0].filled_size
        assert broker.portfolio.position("token").size == 0
        assert broker.portfolio.cash_usdc < config.paper_portfolio_usdc

    asyncio.run(run())


def test_invalid_books_do_not_consume_randomness_or_cooldown(dummy_context):
    async def run():
        ctx = replace(dummy_context, rng=random.Random(1), clock=Mock())
        ctx.clock.now_ms.return_value = 1000
        evaluator = GraphEvaluator(random_example().graph, preview=True)
        state = ctx.rng.getstate()
        crossed = BookSnapshot(
            "token",
            (BookLevel(Decimal("0.6"), Decimal(10)),),
            (BookLevel(Decimal("0.5"), Decimal(10)),),
            1000,
        )
        result = await evaluator.evaluate_and_execute(
            BaseBot.on_book.__name__, ctx, crossed
        )
        assert random_output(result).value is None
        assert not result.intended_orders
        assert ctx.rng.getstate() == state
        valid = replace(crossed, bids=(BookLevel(Decimal("0.4"), Decimal(10)),))
        result = await evaluator.evaluate_and_execute(
            BaseBot.on_book.__name__, ctx, valid
        )
        assert random_output(result).value is not None
        # A missing portfolio cannot be interpreted as a flat account.
        assert not result.intended_orders

    asyncio.run(run())


def test_rejected_buy_leaves_random_template_flat(dummy_context):
    async def run():
        portfolio = PaperPortfolioReader(PaperPortfolio(Decimal(100)))
        broker = Mock(
            submit=AsyncMock(
                return_value=FillEvent.rejected(
                    order_id="rejected",
                    token_id="token",
                    side=Side.BUY,
                    requested_size=Decimal(5),
                    received_at_ms=1000,
                    reject_reason=FillRejectReason.BAD_SIZE,
                    reject_message="below market minimum",
                )
            )
        )
        clock = Mock()
        ctx = replace(
            dummy_context,
            portfolio=portfolio,
            broker=broker,
            clock=clock,
            rng=random.Random(1),
        )
        evaluator = GraphEvaluator(random_example().graph)
        for now in (1000, 1001, 6000, 11000, 16000):
            clock.now_ms.return_value = now
            book = BookSnapshot(
                "token",
                (BookLevel(Decimal("0.4"), Decimal(10)),),
                (BookLevel(Decimal("0.5"), Decimal(10)),),
                now,
            )
            await evaluator.evaluate_and_execute(BaseBot.on_book.__name__, ctx, book)
        assert [call.args[0].side for call in broker.submit.await_args_list] == [
            Side.BUY,
            Side.BUY,
        ]
        assert portfolio.snapshot().position("token").size == 0

    asyncio.run(run())
