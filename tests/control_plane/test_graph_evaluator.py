import asyncio
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from control_plane.graph_fixtures import threshold_buy_graph
from polybot.execution.broker import Broker
from polybot.framework.base import BaseBot
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.dispatch import DispatchSkipReason
from polybot.framework.events import (
    FillEvent,
    FillRejectReason,
    OrderRequest,
    OrderStatus,
    Side,
)
from polybot.framework.events.books import (
    BookGapEvent,
    BookGapReason,
    BookLevel,
    BookSnapshot,
)
from polybot.framework.events.wallet_trades import WalletTradeEvent
from polybot.framework.runner import BotRunner
from polybot.polymarket.markets import Market, MarketOutcome
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.graphs.values import (
    GRAPH_ACTION_ENABLED_HANDLE_ID,
    GRAPH_FIELD_PATH_SEPARATOR,
    GRAPH_VALUE_HANDLE_ID,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphScalarType,
)
from polybot_control_plane.catalog.graphs.types import (
    GraphFieldPath,
    GraphHookName,
)
from polybot_control_plane.catalog.node_based.bot import NodeBasedBot
from polybot_control_plane.catalog.node_based.evaluator import GraphEvaluator
from polybot_control_plane.catalog.node_based.evaluator.contracts import (
    GraphActionSkipReason,
)


def _field_handle(path: str) -> str:
    return GraphFieldPath(
        segments=tuple(path.split(GRAPH_FIELD_PATH_SEPARATOR))
    ).handle_id


class _RecordingBroker(Broker):
    def __init__(self, fill: FillEvent | None = None) -> None:
        self.orders: list[OrderRequest] = []
        self.fill = fill

    async def submit(self, order: OrderRequest) -> FillEvent:
        self.orders.append(order)
        return self.fill or _filled(order)

    async def cancel_all(self) -> None:
        pass


class _CountingBook(BookSnapshot):
    best_ask_reads = 0

    @property
    def best_ask(self) -> BookLevel | None:
        type(self).best_ask_reads += 1
        return super().best_ask


def test_threshold_buy_evaluates_once_in_deterministic_topological_order() -> None:
    broker = _RecordingBroker()
    evaluator = GraphEvaluator(NodeGraph.model_validate(threshold_buy_graph()))

    result = asyncio.run(
        evaluator.evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(ask="0.50"),
        )
    )

    assert result.evaluated_node_ids == (
        "on-book-trigger",
        "constant-threshold",
        "constant-size",
        "comparison-threshold",
        "action-buy",
    )
    assert len(set(result.evaluated_node_ids)) == len(result.evaluated_node_ids)
    assert result.action_results[0].fill is not None
    assert broker.orders == [
        OrderRequest(
            token_id="token",
            side=Side.BUY,
            price=Decimal("0.50"),
            size=Decimal("1.250"),
        )
    ]


def test_shared_computed_path_prefix_is_resolved_once_after_book_guard() -> None:
    graph = threshold_buy_graph()
    graph["nodes"].pop(2)
    size_edge = next(edge for edge in graph["edges"] if edge["id"] == "constant-size")
    size_edge.update(
        source="on-book-trigger",
        source_handle=_field_handle("best_ask.size"),
    )
    broker = _RecordingBroker()
    _CountingBook.best_ask_reads = 0
    book = _CountingBook(
        token_id="token",
        bids=(BookLevel(Decimal("0.48"), Decimal(10)),),
        asks=(BookLevel(Decimal("0.50"), Decimal(10)),),
        received_at_ms=1_000,
        market_slug="market",
        condition_id="condition",
    )

    asyncio.run(
        GraphEvaluator(NodeGraph.model_validate(graph)).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            book,
        )
    )

    # One read validates freshness; the other resolves both graph field paths.
    assert _CountingBook.best_ask_reads == 2


@pytest.mark.parametrize(
    ("comparison_operator", "ask", "threshold", "enabled"),
    (
        (GraphComparisonOperator.EQUAL, "0.5500", "0.55", True),
        (GraphComparisonOperator.NOT_EQUAL, "0.5500", "0.55", False),
        (GraphComparisonOperator.LESS_THAN, "0.54", "0.55", True),
        (GraphComparisonOperator.LESS_THAN_OR_EQUAL, "0.55", "0.55", True),
        (GraphComparisonOperator.GREATER_THAN, "0.56", "0.55", True),
        (GraphComparisonOperator.GREATER_THAN_OR_EQUAL, "0.55", "0.55", True),
        (GraphComparisonOperator.LESS_THAN, "0.56", "0.55", False),
    ),
)
def test_decimal_comparison_operators_are_exact(
    comparison_operator: GraphComparisonOperator,
    ask: str,
    threshold: str,
    enabled: bool,
) -> None:
    graph = threshold_buy_graph()
    graph["nodes"][1]["data"]["value"] = threshold
    graph["nodes"][3]["data"]["operator"] = comparison_operator.value
    broker = _RecordingBroker()

    result = asyncio.run(
        GraphEvaluator(NodeGraph.model_validate(graph)).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(ask=ask),
        )
    )

    assert bool(broker.orders) is enabled
    assert result.action_results[0].skip_reason is (
        None if enabled else GraphActionSkipReason.DISABLED
    )


def test_null_comparison_input_is_false_without_coercion() -> None:
    broker = _RecordingBroker()

    result = asyncio.run(
        GraphEvaluator(
            NodeGraph.model_validate(threshold_buy_graph())
        ).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(ask=None),
        )
    )

    assert broker.orders == []
    assert result.action_results[0].skip_reason is GraphActionSkipReason.DISABLED


def test_nullable_required_action_input_has_stable_skip_reason() -> None:
    broker = _RecordingBroker()

    result = asyncio.run(
        GraphEvaluator(_always_enabled_graph()).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(ask=None),
        )
    )

    assert broker.orders == []
    assert result.action_results[0].skip_reason is (
        GraphActionSkipReason.REQUIRED_INPUT_UNAVAILABLE
    )
    assert result.action_results[0].missing_input_handle_id == "price"


def test_sell_action_extracts_best_bid_and_propagates_optional_identity() -> None:
    broker = _RecordingBroker()
    graph = _always_enabled_graph(
        action=GraphBrokerAction.SUBMIT_SELL,
        price_handle=_field_handle("best_bid.price"),
        optional_inputs=True,
    )

    asyncio.run(
        GraphEvaluator(graph).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(bid="0.48", ask="0.50"),
        )
    )

    assert broker.orders == [
        OrderRequest(
            token_id="token",
            side=Side.SELL,
            price=Decimal("0.48"),
            size=Decimal("1.25"),
            market_slug="market",
            condition_id="condition",
            source_id="graph-source",
            reason="graph-test",
        )
    ]


def test_broker_rejection_remains_an_ordinary_fill_result() -> None:
    rejection = FillEvent.rejected(
        order_id="rejected",
        token_id="token",
        side=Side.BUY,
        requested_size=Decimal("1.25"),
        received_at_ms=1_001,
        reject_reason=FillRejectReason.BAD_PRICE,
        reject_message="bad price",
    )
    broker = _RecordingBroker(rejection)

    result = asyncio.run(
        GraphEvaluator(_always_enabled_graph()).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(ask="0.50"),
        )
    )

    assert result.action_results[0].fill is rejection
    assert result.action_results[0].skip_reason is None


def test_only_the_matching_trigger_branch_is_evaluated() -> None:
    graph = threshold_buy_graph()
    graph["nodes"].append(
        {
            "id": "on-start-trigger",
            "type": GraphNodeType.TRIGGER.value,
            "position": {"x": -200, "y": 0},
            "data": {"hook_name": BaseBot.on_start.__name__},
        }
    )
    evaluator = GraphEvaluator(NodeGraph.model_validate(graph))
    broker = _RecordingBroker()

    start_result = asyncio.run(
        evaluator.evaluate_and_execute(BaseBot.on_start.__name__, _context(broker))
    )
    book_result = asyncio.run(
        evaluator.evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker),
            _book(ask="0.50"),
        )
    )

    assert start_result.evaluated_node_ids == ("on-start-trigger",)
    assert "on-start-trigger" not in book_result.evaluated_node_ids
    assert len(broker.orders) == 1


def test_missing_hook_returns_an_empty_result() -> None:
    result = asyncio.run(
        GraphEvaluator(
            NodeGraph.model_validate(threshold_buy_graph())
        ).evaluate_and_execute(
            BaseBot.on_start.__name__,
            _context(_RecordingBroker()),
        )
    )

    assert result.evaluated_node_ids == ()
    assert result.action_results == ()


def test_book_gap_branch_never_submits_an_order() -> None:
    broker = _RecordingBroker()
    graph = _always_enabled_graph_for_book_gap()

    result = asyncio.run(
        GraphEvaluator(graph).evaluate_and_execute(
            BaseBot.on_book_gap.__name__,
            _context(broker),
            BookGapEvent(
                condition_id="condition",
                observed_at_ms=1_000,
                reason=BookGapReason.BOOK_STREAM_GAP,
            ),
        )
    )

    assert broker.orders == []
    assert result.action_results[0].skip_reason is GraphActionSkipReason.BOOK_GAP


def test_each_sequential_action_rechecks_book_freshness() -> None:
    graph = threshold_buy_graph()
    first_action = next(node for node in graph["nodes"] if node["id"] == "action-buy")
    graph["nodes"].append({**first_action, "id": "action-buy-second"})
    graph["edges"].extend(
        {
            **edge,
            "id": f"{edge['id']}-second",
            "target": "action-buy-second",
        }
        for edge in tuple(graph["edges"])
        if edge["target"] == "action-buy"
    )
    clock = _FixedClock()

    class _AgingBroker(_RecordingBroker):
        async def submit(self, order: OrderRequest) -> FillEvent:
            fill = await super().submit(order)
            clock.now = 2_000
            return fill

    broker = _AgingBroker()
    result = asyncio.run(
        GraphEvaluator(NodeGraph.model_validate(graph)).evaluate_and_execute(
            BaseBot.on_book.__name__,
            _context(broker, clock=clock),
            _book(ask="0.50"),
        )
    )

    assert len(broker.orders) == 1
    assert result.action_results[0].fill is not None
    assert result.action_results[1].skip_reason is GraphActionSkipReason.BOOK_STALE


def test_each_sequential_action_rechecks_wallet_trade_freshness() -> None:
    graph = _always_enabled_graph(
        hook_name=BaseBot.on_wallet_trade.__name__,
        price_handle=_field_handle("price"),
        optional_inputs=True,
    ).model_dump(mode="json")
    first_action = next(node for node in graph["nodes"] if node["id"] == "action")
    graph["nodes"].append({**first_action, "id": "action-second"})
    graph["edges"].extend(
        {
            **edge,
            "id": f"{edge['id']}-second",
            "target": "action-second",
        }
        for edge in tuple(graph["edges"])
        if edge["target"] == "action"
    )
    clock = _FixedClock()

    class _AgingBroker(_RecordingBroker):
        async def submit(self, order: OrderRequest) -> FillEvent:
            fill = await super().submit(order)
            clock.now = 2_000
            return fill

    trade = WalletTradeEvent(
        wallet="0x0000000000000000000000000000000000000001",
        condition_id="condition",
        token_id="token",
        side=Side.BUY,
        size=Decimal("2"),
        price=Decimal("0.50"),
        source_id="trade-1",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_000,
        market_slug="market",
    )
    broker = _AgingBroker()

    result = asyncio.run(
        GraphEvaluator(NodeGraph.model_validate(graph)).evaluate_and_execute(
            BaseBot.on_wallet_trade.__name__,
            _context(broker, clock=clock),
            trade,
        )
    )

    assert len(broker.orders) == 1
    assert result.action_results[0].fill is not None
    assert result.action_results[1].skip_reason is (
        GraphActionSkipReason.WALLET_TRADE_STALE
    )


def test_wallet_trade_action_rechecks_future_dated_payload() -> None:
    graph = _always_enabled_graph(
        hook_name=BaseBot.on_wallet_trade.__name__,
        price_handle=_field_handle("price"),
    )
    trade = WalletTradeEvent(
        wallet="0x0000000000000000000000000000000000000001",
        condition_id="condition",
        token_id="token",
        side=Side.BUY,
        size=Decimal("2"),
        price=Decimal("0.50"),
        source_id="trade-1",
        trade_timestamp_ms=1_000,
        observed_at_ms=1_000,
        market_slug="market",
    )
    trade = replace(trade, observed_at_ms=2_000)
    broker = _RecordingBroker()

    result = asyncio.run(
        GraphEvaluator(graph).evaluate_and_execute(
            BaseBot.on_wallet_trade.__name__,
            _context(broker),
            trade,
        )
    )

    assert broker.orders == []
    assert result.action_results[0].skip_reason is (
        GraphActionSkipReason.WALLET_TRADE_FUTURE_DATED
    )


def test_repeated_true_events_submit_without_hidden_rearming_state() -> None:
    broker = _RecordingBroker()
    bot = NodeBasedBot(NodeGraph.model_validate(threshold_buy_graph()))
    ctx = _context(broker)

    async def evaluate_events() -> None:
        await bot.on_book(ctx, _book(ask="0.50"))
        await bot.on_book(ctx, _book(ask="0.60"))
        await bot.on_book(ctx, _book(ask="0.50"))

    asyncio.run(evaluate_events())

    assert len(broker.orders) == 2


@pytest.mark.parametrize(
    ("book_kind", "reason"),
    (
        ("stale", DispatchSkipReason.BOOK_STALE),
        ("future", DispatchSkipReason.BOOK_FUTURE_DATED),
        ("bad-timestamp", DispatchSkipReason.BAD_BOOK_TIMESTAMP),
        ("crossed", DispatchSkipReason.BOOK_CROSSED),
        ("malformed", DispatchSkipReason.BAD_BOOK_LEVEL),
    ),
)
def test_runtime_book_guards_reject_before_graph_evaluation(
    book_kind: str,
    reason: DispatchSkipReason,
) -> None:
    broker = _RecordingBroker()
    runner = BotRunner(
        NodeBasedBot(NodeGraph.model_validate(threshold_buy_graph())),
        _context(broker),
        now_ms_fn=lambda: 1_000,
    )
    books = {
        "stale": _book(ask="0.50", received_at_ms=0),
        "future": _book(ask="0.50", received_at_ms=2_000),
        "bad-timestamp": _book(ask="0.50", received_at_ms=-1),
        "crossed": _book(bid="0.60", ask="0.50"),
        "malformed": _book(ask="0.50", ask_size="0"),
    }

    outcome = asyncio.run(runner.dispatch_book(books[book_kind]))

    assert outcome.skip_reason is reason
    assert broker.orders == []


@pytest.mark.parametrize(
    "market_case",
    (
        "missing",
        "slug-mismatch",
        "condition-mismatch",
        "token-mismatch",
    ),
)
def test_runtime_book_guard_rejects_contradictory_market_identity(
    market_case: str,
) -> None:
    broker = _RecordingBroker()
    context = _context(broker)
    markets = {
        "missing": None,
        "slug-mismatch": replace(_market(), slug="other-market"),
        "condition-mismatch": replace(
            _market(), condition_id="other-condition"
        ),
        "token-mismatch": _market(token_id="other-token"),
    }
    context.markets.find_by_slug.return_value = markets[market_case]
    runner = BotRunner(
        NodeBasedBot(NodeGraph.model_validate(threshold_buy_graph())),
        context,
        now_ms_fn=lambda: 1_000,
    )
    runner.set_runtime_market_slugs(frozenset({"market"}))

    outcome = asyncio.run(runner.dispatch_book(_book(ask="0.50")))

    assert outcome.skip_reason is DispatchSkipReason.BOOK_IDENTITY_MISMATCH
    assert broker.orders == []


def _always_enabled_graph(
    *,
    action: GraphBrokerAction = GraphBrokerAction.SUBMIT_BUY,
    hook_name: GraphHookName = BaseBot.on_book.__name__,
    price_handle: str = _field_handle("best_ask.price"),
    optional_inputs: bool = False,
) -> NodeGraph:
    nodes = [
        {
            "id": "trigger",
            "type": GraphNodeType.TRIGGER.value,
            "position": {"x": 0, "y": 0},
            "data": {"hook_name": hook_name},
        },
        {
            "id": "enabled",
            "type": GraphNodeType.CONSTANT.value,
            "position": {"x": 0, "y": 100},
            "data": {"scalar_type": GraphScalarType.BOOLEAN.value, "value": True},
        },
        {
            "id": "size",
            "type": GraphNodeType.CONSTANT.value,
            "position": {"x": 0, "y": 200},
            "data": {"scalar_type": GraphScalarType.DECIMAL.value, "value": "1.25"},
        },
        {
            "id": "action",
            "type": GraphNodeType.BROKER_ACTION.value,
            "position": {"x": 300, "y": 0},
            "data": {"action": action.value},
        },
    ]
    edges = [
        _edge(
            "enabled-action",
            "enabled",
            GRAPH_VALUE_HANDLE_ID,
            GRAPH_ACTION_ENABLED_HANDLE_ID,
        ),
        _edge("token-action", "trigger", _field_handle("token_id"), "token_id"),
        _edge("price-action", "trigger", price_handle, "price"),
        _edge("size-action", "size", GRAPH_VALUE_HANDLE_ID, "size"),
    ]
    if optional_inputs:
        nodes.extend(
            (
                {
                    "id": "source",
                    "type": GraphNodeType.CONSTANT.value,
                    "position": {"x": 0, "y": 300},
                    "data": {
                        "scalar_type": GraphScalarType.STRING.value,
                        "value": "graph-source",
                    },
                },
                {
                    "id": "reason",
                    "type": GraphNodeType.CONSTANT.value,
                    "position": {"x": 0, "y": 400},
                    "data": {
                        "scalar_type": GraphScalarType.STRING.value,
                        "value": "graph-test",
                    },
                },
            )
        )
        edges.extend(
            (
                _edge(
                    "market-action",
                    "trigger",
                    _field_handle("market_slug"),
                    "market_slug",
                ),
                _edge(
                    "condition-action",
                    "trigger",
                    _field_handle("condition_id"),
                    "condition_id",
                ),
                _edge(
                    "source-action",
                    "source",
                    GRAPH_VALUE_HANDLE_ID,
                    "source_id",
                ),
                _edge(
                    "reason-action",
                    "reason",
                    GRAPH_VALUE_HANDLE_ID,
                    "reason",
                ),
            )
        )
    return NodeGraph.model_validate({"nodes": nodes, "edges": edges})


def _always_enabled_graph_for_book_gap() -> NodeGraph:
    graph = _always_enabled_graph().model_dump(mode="json")
    trigger = next(node for node in graph["nodes"] if node["id"] == "trigger")
    trigger["data"]["hook_name"] = BaseBot.on_book_gap.__name__
    graph["nodes"].extend(
        (
            {
                "id": "token",
                "type": GraphNodeType.CONSTANT.value,
                "position": {"x": 0, "y": 300},
                "data": {
                    "scalar_type": GraphScalarType.STRING.value,
                    "value": "token",
                },
            },
            {
                "id": "price",
                "type": GraphNodeType.CONSTANT.value,
                "position": {"x": 0, "y": 400},
                "data": {
                    "scalar_type": GraphScalarType.DECIMAL.value,
                    "value": "0.50",
                },
            },
        )
    )
    for edge in graph["edges"]:
        if edge["id"] == "token-action":
            edge.update(source="token", source_handle=GRAPH_VALUE_HANDLE_ID)
        elif edge["id"] == "price-action":
            edge.update(source="price", source_handle=GRAPH_VALUE_HANDLE_ID)
    graph["edges"].append(
        _edge(
            "condition-action",
            "trigger",
            _field_handle("condition_id"),
            "condition_id",
        )
    )
    return NodeGraph.model_validate(graph)


def _edge(
    edge_id: str,
    source: str,
    source_handle: str,
    target_handle: str,
) -> dict[str, str]:
    return {
        "id": edge_id,
        "source": source,
        "source_handle": source_handle,
        "target": "action",
        "target_handle": target_handle,
    }


def _context(broker: Broker, *, clock: "_FixedClock | None" = None) -> BotContext:
    markets = AsyncMock()
    markets.find_by_slug.return_value = _market()
    return BotContext(
        config=BotConfig(name="graph", event_max_age_ms=500),
        broker=broker,
        markets=markets,
        books=AsyncMock(),
        wallet_activity=AsyncMock(),
        clock=clock or _FixedClock(),
    )


def _market(*, token_id: str = "token") -> Market:
    return Market(
        condition_id="condition",
        slug="market",
        question="Test market",
        minimum_tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("1"),
        neg_risk=False,
        fee_rate=Decimal(0),
        outcomes=(
            MarketOutcome("Yes", token_id),
            MarketOutcome("No", "opposite-token"),
        ),
    )


class _FixedClock:
    def __init__(self) -> None:
        self.now = 1_000

    def now_ms(self) -> int:
        return self.now

    async def sleep(self, seconds: float) -> None:
        pass


def _book(
    *,
    bid: str = "0.48",
    ask: str | None,
    ask_size: str = "10",
    received_at_ms: int = 1_000,
) -> BookSnapshot:
    return BookSnapshot(
        token_id="token",
        bids=(BookLevel(Decimal(bid), Decimal(10)),),
        asks=(() if ask is None else (BookLevel(Decimal(ask), Decimal(ask_size)),)),
        received_at_ms=received_at_ms,
        market_slug="market",
        condition_id="condition",
    )


def _filled(order: OrderRequest) -> FillEvent:
    return FillEvent(
        order_id=f"order-{len(order.token_id)}",
        token_id=order.token_id,
        side=order.side,
        status=OrderStatus.FILLED,
        requested_size=order.size,
        filled_size=order.size,
        average_price=order.price,
        fee_usdc=Decimal(0),
        received_at_ms=1_001,
    )
