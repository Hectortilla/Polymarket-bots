from __future__ import annotations

from api.catalog.graphs.preview_samples import DEFAULT_PREVIEW_CASH
from api.catalog.graphs.values import GraphPort
from fastapi import status
from polybot.framework.base import BaseBot
from polybot.framework.config.constants import DEFAULT_EVENT_MAX_AGE_MS
from polybot.framework.events.wallet_trades import WalletTradeValidationIssue

"""MVP graph contract and execution behavior at public boundaries."""

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from api.catalog.graphs.catalog import GRAPH_NODE_CATALOG
from api.catalog.graphs.catalog.triggers import GraphTriggerDescriptor
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.examples.entry_exit import entry_exit_example
from api.catalog.graphs.examples.multiple_conditions import multiple_conditions_example
from api.catalog.graphs.operations import OPERATION_DESCRIPTORS
from api.catalog.graphs.preview import (
    GraphPreviewRequest,
    PreviewPortfolio,
)
from api.catalog.graphs.reasons import GraphReason
from api.catalog.graphs.value_status import GraphValueStatus
from api.catalog.graphs.values import (
    GraphNodeType,
    GraphOperation,
    GraphScalarType,
)
from api.catalog.node_based.evaluator import (
    GraphEvaluator,
    capabilities,
    event_controls,
)
from api.catalog.node_based.evaluator.diagnostics import (
    GraphDiagnostics,
)
from api.catalog.node_based.evaluator.event_controls import (
    EventControlState,
)
from api.catalog.node_based.evaluator.pure import evaluate_pure
from api.catalog.node_based.evaluator.values import RuntimeValue
from api.catalog.node_based.preview import (
    PreviewBroker,
    PreviewClock,
    preview_graph,
)
from api.http.routes.paths import (
    GRAPH_PREVIEW_PATH,
    api_route_path,
)
from conftest import DummyBroker
from polybot.execution.paper.portfolio import PaperPortfolio
from polybot.execution.paper.portfolio_reader import PaperPortfolioReader
from polybot.framework.config.models import BotConfig
from polybot.framework.context import BotContext
from polybot.framework.events import FillEvent, FillRejectReason, OrderStatus, Side
from polybot.framework.events.books import (
    BookGapEvent,
    BookGapReason,
    BookLevel,
    BookSnapshot,
)
from polybot.framework.events.resolutions import MarketResolutionEvent
from pydantic import TypeAdapter, ValidationError

from control_plane.auth_fixtures import authenticated_test_client as TestClient
from control_plane.auth_fixtures import create_authenticated_app as create_app
from control_plane.graph_fixtures import threshold_buy_graph
from control_plane.graph_preview_fixture import preview_fixture


def operation_graph(
    operation: GraphOperation,
    values: dict[str, object],
    *,
    input_ids: tuple[str, ...] = (),
) -> dict:
    nodes = [
        dict(
            id="trigger",
            type=GraphNodeType.TRIGGER,
            position=dict(x=0, y=0),
            data=dict(hook_name="on_start"),
        ),
        dict(
            id="operation",
            type=GraphNodeType.OPERATION,
            position=dict(x=200, y=0),
            data=dict(operation=operation.value, input_ids=list(input_ids)),
        ),
    ]
    edges = []
    descriptor = OPERATION_DESCRIPTORS[operation]
    for port in descriptor.inputs:
        if port.handle_id == GraphPort.CONTEXT:
            edges.append(
                edge("trigger", GraphPort.CONTEXT, "operation", GraphPort.CONTEXT)
            )
    for name, value in values.items():
        kind = (
            GraphScalarType.BOOLEAN
            if isinstance(value, bool)
            else (
                GraphScalarType.NUMBER
                if isinstance(value, (int, Decimal))
                else GraphScalarType.STRING
            )
        )
        nodes.append(
            dict(
                id=name,
                type=GraphNodeType.CONSTANT,
                position=dict(x=0, y=100),
                data=dict(
                    scalar_type=kind.value,
                    value=str(value) if kind is GraphScalarType.NUMBER else value,
                ),
            )
        )
        edges.append(edge(name, GraphPort.VALUE, "operation", name))
    if not descriptor.terminal:
        nodes.append(
            dict(
                id="inspect",
                type=GraphNodeType.OPERATION,
                position=dict(x=400, y=0),
                data=dict(operation=GraphOperation.INSPECT.value),
            )
        )
        edges.extend(
            [
                edge("trigger", GraphPort.CONTEXT, "inspect", GraphPort.CONTEXT),
                edge(
                    "operation",
                    descriptor.outputs[0].handle_id,
                    "inspect",
                    GraphPort.VALUE,
                ),
            ]
        )
    return dict(nodes=nodes, edges=edges)


def edge(source: str, output: str, target: str, input_: str) -> dict:
    return dict(
        id=f"{source}-{output}-{target}-{input_}",
        source=source,
        source_handle=output,
        target=target,
        target_handle=input_,
    )


def test_catalog_exposes_all_operations_and_one_numeric_constant():
    assert {item.operation for item in GRAPH_NODE_CATALOG.operations} == set(
        GraphOperation
    )
    assert [item.scalar_type for item in GRAPH_NODE_CATALOG.constants] == [
        GraphScalarType.BOOLEAN,
        GraphScalarType.NUMBER,
        GraphScalarType.STRING,
    ]


def test_number_strings_round_trip_without_precision_loss():
    graph = operation_graph(
        GraphOperation.ADD,
        dict(left=Decimal("9007199254740993"), right=Decimal("0.000000000000000001")),
    )
    parsed = NodeGraph.model_validate(graph)
    assert (
        parsed.model_dump(mode="json")["nodes"][2]["data"]["value"]
        == "9007199254740993"
    )
    assert NodeGraph.model_validate_json(parsed.model_dump_json()) == parsed


def test_diagnostic_only_branch_and_expandable_ports():
    graph = operation_graph(
        GraphOperation.AND, dict(first=True, third=False), input_ids=("first", "third")
    )
    NodeGraph.model_validate(graph)
    graph["nodes"][1]["data"]["input_ids"] = ["first", "first"]
    with pytest.raises(ValidationError, match="unique handles"):
        NodeGraph.model_validate(graph)


def test_compiler_rejects_unsupported_operation_before_any_execution(monkeypatch):
    graph = NodeGraph.model_validate(
        operation_graph(GraphOperation.ADD, dict(left=1, right=2))
    )
    monkeypatch.setattr(capabilities, "EXECUTABLE_OPERATIONS", frozenset())
    with pytest.raises(capabilities.UnsupportedGraphOperation, match="operation"):
        GraphEvaluator(graph)


def context(now=1000, portfolio=None):
    return BotContext(
        config=BotConfig(name="test"),
        broker=PreviewBroker(),
        markets=AsyncMock(),
        books=AsyncMock(),
        wallet_activity=AsyncMock(),
        clock=PreviewClock(now),
        portfolio=portfolio,
    )


def operation_result(graph, ctx=None, payload=None):
    result = asyncio.run(
        GraphEvaluator(NodeGraph.model_validate(graph)).evaluate_and_execute(
            "on_start", ctx or context(), payload
        )
    )
    return next(node for node in result.nodes if node.node_id == "operation")


@pytest.mark.parametrize(
    "operation,values,expected",
    [
        (GraphOperation.ADD, dict(left=Decimal("0.1"), right=Decimal("0.2")), "0.3"),
        (GraphOperation.SUBTRACT, dict(left=3, right=2), "1"),
        (GraphOperation.MULTIPLY, dict(left=3, right=2), "6"),
        (
            GraphOperation.DIVIDE,
            dict(left=1, right=3),
            "0.3333333333333333333333333333",
        ),
        (GraphOperation.MIN, dict(left=3, right=2), "2"),
        (GraphOperation.MAX, dict(left=3, right=2), "3"),
        (GraphOperation.AND, dict(input_1=True, input_2=False), False),
        (GraphOperation.OR, dict(input_1=True, input_2=False), True),
        (GraphOperation.NOT, dict(value=True), False),
        (GraphOperation.BETWEEN, dict(value=2, minimum=2, maximum=3), True),
        (GraphOperation.CLAMP, dict(value=5, minimum=2, maximum=3), "3"),
        (GraphOperation.ROUND, dict(value=Decimal("-2.345"), places=2), "-2.35"),
        (
            GraphOperation.ROUND,
            dict(value=Decimal("2.345"), places=Decimal("2.0")),
            "2.35",
        ),
        (GraphOperation.IS_PRESENT, dict(value=0), True),
        (GraphOperation.SELECT, dict(condition=False, when_true=1, when_false=2), "2"),
    ],
)
def test_pure_operations(operation, values, expected):
    read = operation_result(operation_graph(operation, values))
    assert next(iter(read.outputs.values())).value == expected


@pytest.mark.parametrize(
    "operation,values,reason",
    [
        (GraphOperation.DIVIDE, dict(left=1, right=0), GraphReason.DIVISION_BY_ZERO),
        (
            GraphOperation.CLAMP,
            dict(value=1, minimum=3, maximum=2),
            GraphReason.INVALID_BOUNDS,
        ),
        (
            GraphOperation.BETWEEN,
            dict(value=1, minimum=3, maximum=2),
            GraphReason.INVALID_BOUNDS,
        ),
        (
            GraphOperation.ROUND,
            dict(value=1, places=Decimal("2.7")),
            GraphReason.WHOLE_NUMBER_REQUIRED,
        ),
    ],
)
def test_invalid_arithmetic_has_structured_reason(operation, values, reason):
    read = operation_result(operation_graph(operation, values))
    assert read.status is GraphValueStatus.INVALID
    assert read.reason == reason


def test_missing_comparison_through_not_never_enables_order():

    graph = threshold_buy_graph()
    graph["nodes"].append(
        dict(
            id="invert",
            type=GraphNodeType.OPERATION,
            position=dict(x=0, y=0),
            data=dict(operation=GraphOperation.NOT),
        )
    )
    for connection in graph["edges"]:
        if connection["target_handle"] == GraphPort.ENABLED:
            connection.update(source="invert", source_handle=GraphPort.RESULT)
    graph["edges"].append(
        edge("comparison-threshold", GraphPort.RESULT, "invert", GraphPort.VALUE)
    )
    book = BookSnapshot("token", (), (), 1000)
    result = asyncio.run(
        GraphEvaluator(
            NodeGraph.model_validate(graph), preview=True
        ).evaluate_and_execute("on_book", context(), book)
    )
    assert not result.intended_orders
    assert result.action_results[0].skip_reason == GraphReason.MISSING


def test_select_ignores_missing_unselected_value_and_is_present_distinguishes_invalid():

    missing = RuntimeValue.from_value(None)
    invalid = RuntimeValue.invalid(GraphReason.INVALID_NUMBER)
    selected = evaluate_pure(
        GraphOperation.SELECT,
        {
            GraphPort.CONDITION: RuntimeValue(True),
            GraphPort.WHEN_TRUE: RuntimeValue(Decimal(2)),
            GraphPort.WHEN_FALSE: missing,
        },
    )
    assert selected.value == 2
    assert (
        evaluate_pure(GraphOperation.IS_PRESENT, {GraphPort.VALUE: missing}).value
        is False
    )
    assert (
        evaluate_pure(GraphOperation.IS_PRESENT, {GraphPort.VALUE: invalid}) == invalid
    )


@pytest.mark.parametrize(
    "operation",
    [GraphOperation.COOLDOWN, GraphOperation.ONCE, GraphOperation.DEDUPLICATE],
)
def test_event_control_consumes_only_enabled_signals_and_isolates_keys(operation):
    values = dict(enabled=False, key="token")
    if operation is GraphOperation.COOLDOWN:
        values["duration_ms"] = 100
    graph = operation_graph(operation, values)
    evaluator = GraphEvaluator(NodeGraph.model_validate(graph))

    async def run():
        ctx = context()
        first = await evaluator.evaluate_and_execute("on_start", ctx)
        assert (
            not next(n for n in first.nodes if n.node_id == "operation")
            .outputs[GraphPort.RESULT]
            .value
        )
        # A fresh enabled graph has its own run state; repeated events use the same evaluator.
        for node in graph["nodes"]:
            if node["id"] == GraphPort.ENABLED:
                node["data"]["value"] = True
        active = GraphEvaluator(NodeGraph.model_validate(graph))
        reads = [await active.evaluate_and_execute("on_start", ctx) for _ in range(2)]
        assert [
            next(n for n in r.nodes if n.node_id == "operation")
            .outputs[GraphPort.RESULT]
            .value
            for r in reads
        ] == [True, False]
        if operation is GraphOperation.COOLDOWN:
            ctx.clock._now_ms += 100
            third = await active.evaluate_and_execute("on_start", ctx)
            assert (
                next(n for n in third.nodes if n.node_id == "operation")
                .outputs[GraphPort.RESULT]
                .value
                is True
            )

    asyncio.run(run())


def test_once_reset_and_capacity_never_evict_claims(monkeypatch):

    monkeypatch.setattr(event_controls, "MAX_STATE_KEYS_PER_NODE", 1)
    state = EventControlState()
    inputs = {GraphPort.ENABLED: RuntimeValue(True), GraphPort.KEY: RuntimeValue("a")}
    assert state.evaluate("node", GraphOperation.ONCE, inputs, 0).value is True
    assert (
        state.evaluate(
            "node", GraphOperation.ONCE, {**inputs, GraphPort.KEY: RuntimeValue("b")}, 0
        ).reason
        == GraphReason.STATE_CAPACITY
    )
    assert state.evaluate("node", GraphOperation.ONCE, inputs, 0).value is False
    assert (
        state.evaluate(
            "node",
            GraphOperation.ONCE,
            {**inputs, GraphPort.RESET: RuntimeValue(True)},
            0,
        ).reason
        == GraphReason.RESET
    )
    assert state.evaluate("node", GraphOperation.ONCE, inputs, 0).value is True


def test_gap_does_not_consume_or_rearm_state():
    evaluator = GraphEvaluator(
        NodeGraph.model_validate(
            operation_graph(GraphOperation.ONCE, dict(enabled=True, key="a"))
        )
    )
    gap = BookGapEvent(None, 1000, BookGapReason.BOOK_STREAM_GAP)

    async def run():
        ctx = context()
        results = [
            await evaluator.evaluate_and_execute("on_start", ctx, gap),
            await evaluator.evaluate_and_execute("on_start", ctx),
            await evaluator.evaluate_and_execute("on_start", ctx, gap),
            await evaluator.evaluate_and_execute("on_start", ctx),
        ]
        values = [
            next(n for n in r.nodes if n.node_id == "operation").outputs[
                GraphPort.RESULT
            ]
            for r in results
        ]
        assert [v.value for v in values] == [None, True, None, False]

    asyncio.run(run())


def test_portfolio_reads_use_immutable_paper_accounting():
    portfolio = PaperPortfolio(Decimal("100"))
    reader = PaperPortfolioReader(portfolio)
    before = reader.snapshot()
    portfolio.apply_fill(
        token_id="token",
        side=Side.BUY,
        filled_size=Decimal(2),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal(0),
    )
    after = reader.snapshot()
    assert before.available_cash == 100 and not before.positions
    assert after.available_cash == Decimal("99.2")
    assert after.position("token").size == 2
    read = operation_result(
        operation_graph(GraphOperation.POSITION, dict(token_id="token")),
        context(portfolio=reader),
    )
    assert read.outputs[GraphPort.SIZE].value == "2"
    assert read.outputs[GraphPort.HAS_POSITION].value is True
    assert read.outputs[GraphPort.AVERAGE_ENTRY_PRICE].value == "0.4"
    missing = operation_result(
        operation_graph(GraphOperation.POSITION, dict(token_id="absent")),
        context(portfolio=reader),
    )
    assert missing.outputs[GraphPort.SIZE].value == "0"
    unavailable = operation_result(operation_graph(GraphOperation.BALANCE, {}))
    assert (
        unavailable.outputs[GraphPort.AVAILABLE_CASH].reason
        == GraphReason.PORTFOLIO_UNAVAILABLE
    )


@pytest.mark.parametrize(
    "trigger", GRAPH_NODE_CATALOG.triggers, ids=lambda trigger: trigger.hook_name
)
def test_catalog_samples_match_preview_event_contracts(trigger: GraphTriggerDescriptor):
    assert (trigger.sample_payload is None) == (trigger.payload is None)
    request = GraphPreviewRequest.model_validate_json(
        json.dumps(
            dict(
                graph=dict(
                    nodes=[
                        dict(
                            id="trigger",
                            type=GraphNodeType.TRIGGER,
                            position=dict(x=0, y=0),
                            data=dict(hook_name=trigger.hook_name),
                        )
                    ]
                ),
                hook_name=trigger.hook_name,
                payload=trigger.sample_payload,
                now_ms=trigger.sample_time_ms,
                portfolio=dict(
                    positions=GRAPH_NODE_CATALOG.model_dump(mode="json")[
                        "sample_positions"
                    ]
                ),
            )
        )
    )
    assert (
        TypeAdapter(type(request.event)).dump_python(request.event, mode="json")
        == trigger.sample_payload
    )
    assert request.portfolio.positions == GRAPH_NODE_CATALOG.sample_positions


def test_preview_plans_orders_without_submitting_or_fabricating_fills():

    request = GraphPreviewRequest(
        graph=threshold_buy_graph(),
        hook_name="on_book",
        now_ms=1000,
        payload=dict(
            token_id="token",
            bids=[dict(price="0.39", size="100")],
            asks=[dict(price="0.4", size="100")],
            received_at_ms=1000,
        ),
    )
    result = asyncio.run(preview_graph(request))
    assert len(result.intended_orders) == 1
    action = next(n for n in result.nodes if n.node_id == "action-buy")
    assert action.outputs[GraphPort.STATUS].value == GraphValueStatus.PLANNED.value
    assert action.outputs[GraphPort.FILLED_SIZE].value is None
    assert request.portfolio.available_cash == DEFAULT_PREVIEW_CASH


def test_preview_http_endpoint_and_sample_errors():

    fixture = preview_fixture()
    client = TestClient(create_app())
    response = client.post(api_route_path(GRAPH_PREVIEW_PATH), json=fixture["request"])
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == fixture["response"]
    fixture["request"]["payload"]["received_at_ms"] = "not-a-time"
    response = client.post(api_route_path(GRAPH_PREVIEW_PATH), json=fixture["request"])
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert any(
        "received_at_ms" in str(issue["loc"]) for issue in response.json()["detail"]
    )


def test_examples_enter_hold_and_exit_with_paper_accounting():

    class AccountingBroker(DummyBroker):
        async def submit(self, order):
            fill = await super().submit(order)
            portfolio.apply_fill(
                token_id=fill.token_id,
                side=fill.side,
                filled_size=fill.filled_size,
                average_price=fill.average_price,
                fee_usdc=fill.fee_usdc,
            )
            return fill

    portfolio = PaperPortfolio(Decimal(100))
    broker = AccountingBroker([])
    ctx = replace(context(portfolio=PaperPortfolioReader(portfolio)), broker=broker)

    async def run():
        evaluator = GraphEvaluator(entry_exit_example().graph)
        cheap = BookSnapshot(
            "token",
            (BookLevel(Decimal("0.39"), Decimal(10)),),
            (BookLevel(Decimal("0.40"), Decimal(10)),),
            1000,
        )
        await evaluator.evaluate_and_execute("on_book", ctx, cheap)
        await evaluator.evaluate_and_execute("on_book", ctx, cheap)
        assert len(broker.submitted) == 1
        expensive = replace(
            cheap,
            bids=(BookLevel(Decimal("0.65"), Decimal(10)),),
            asks=(BookLevel(Decimal("0.66"), Decimal(10)),),
        )
        await evaluator.evaluate_and_execute("on_book", ctx, expensive)
        assert [order.side for order in broker.submitted] == [Side.BUY, Side.SELL]
        assert portfolio.position("token").size == 0
        assert portfolio.cash_usdc > 100
        result = await GraphEvaluator(
            multiple_conditions_example().graph, preview=True
        ).evaluate_and_execute("on_book", ctx, cheap)
        assert len(result.intended_orders) == 1

    asyncio.run(run())


def test_diagnostics_coalesce_repeats_and_report_suppressed_count():

    sink = AsyncMock()
    ctx = replace(context(), activity=sink)
    diagnostics = GraphDiagnostics()

    async def run():
        for _ in range(3):
            await diagnostics.emit(ctx, "node", "same")
        assert sink.emit.await_count == 1
        ctx.clock._now_ms += 1000
        await diagnostics.emit(ctx, "node", "same")
        assert sink.emit.await_count == 2
        assert "2 repeated messages suppressed" in sink.emit.await_args.args[0]

    asyncio.run(run())


def test_frontend_preview_fixture_is_generated_from_backend():
    path = (
        Path(__file__).parents[3] / "frontend/src/lib/catalog/graphPreview.fixture.json"
    )
    assert json.loads(path.read_text()) == preview_fixture()


@pytest.mark.parametrize(
    "status", (OrderStatus.FILLED, OrderStatus.PARTIAL, OrderStatus.REJECTED)
)
def test_action_outputs_preserve_real_fill_status_and_reason(status):
    graph = NodeGraph.model_validate(threshold_buy_graph())
    size = Decimal("2")
    rejected = status is OrderStatus.REJECTED
    fill = FillEvent(
        order_id="test-order",
        token_id="token",
        side=Side.BUY,
        status=status,
        requested_size=size,
        filled_size=(
            Decimal(0)
            if rejected
            else size
            if status is OrderStatus.FILLED
            else size / 2
        ),
        average_price=None if rejected else Decimal("0.4"),
        fee_usdc=Decimal(0),
        received_at_ms=1000,
        reject_reason=FillRejectReason.BAD_SIZE if rejected else None,
        reject_message="Invalid size" if rejected else None,
    )
    broker = AsyncMock()
    broker.submit.return_value = fill
    ctx = replace(context(), broker=broker)
    book = BookSnapshot(
        "token",
        (BookLevel(Decimal("0.39"), Decimal(10)),),
        (BookLevel(Decimal("0.40"), Decimal(10)),),
        1000,
    )
    result = asyncio.run(
        GraphEvaluator(graph).evaluate_and_execute("on_book", ctx, book)
    )
    action = next(n for n in result.nodes if n.node_id == "action-buy")
    assert action.outputs[GraphPort.STATUS].value == status.value
    assert action.outputs[GraphPort.FILLED_SIZE].value == str(fill.filled_size)
    assert action.outputs[GraphPort.AVERAGE_PRICE].value == (
        None if rejected else "0.4"
    )
    assert action.outputs[GraphPort.REJECT_REASON].value == fill.reject_reason
    assert action.outputs[GraphPort.SKIP_REASON].value is None
    broker.submit.assert_awaited_once()


def test_portfolio_snapshot_preserves_shorts_and_observes_settlement():
    portfolio = PaperPortfolio(Decimal("100"))
    reader = PaperPortfolioReader(portfolio)
    portfolio.apply_fill(
        token_id="token",
        side=Side.SELL,
        filled_size=Decimal(2),
        average_price=Decimal("0.4"),
        fee_usdc=Decimal(0),
    )
    before = reader.snapshot()
    assert before.position("token").size == -2
    read = operation_result(
        operation_graph(GraphOperation.POSITION, dict(token_id="token")),
        context(portfolio=reader),
    )
    assert read.outputs[GraphPort.SIZE].value == "-2"
    assert read.outputs[GraphPort.HAS_POSITION].value is True
    portfolio.settle_market(
        MarketResolutionEvent(
            condition_id="condition",
            market_slug="market",
            token_ids=("token", "other"),
            winning_token_id="token",
            winning_outcome="Yes",
            resolved_at_ms=1000,
            source="test",
        )
    )
    after = reader.snapshot()
    assert after.position("token").size == 0
    assert after.available_cash == Decimal("98.8")
    assert before.position("token").size == -2


def test_one_snapshot_per_event_and_preview_matches_paper_decisions():
    graph = multiple_conditions_example().graph
    provider = Mock(wraps=PreviewPortfolio())
    broker = DummyBroker([])
    ctx = replace(context(portfolio=provider), broker=broker)
    fixture = preview_fixture()
    request = GraphPreviewRequest(**{**fixture["request"], "graph": graph})

    async def run():
        preview = await preview_graph(request)
        evaluator = GraphEvaluator(graph)
        first = await evaluator.evaluate_and_execute(
            request.hook_name, ctx, request.event
        )
        assert tuple(broker.submitted) == preview.intended_orders
        for preview_node, paper_node in zip(preview.nodes, first.nodes, strict=True):
            if preview_node.node_id not in ("buy", "explain"):
                assert preview_node == paper_node
        assert len(first.evaluated_node_ids) == len(set(first.evaluated_node_ids))
        provider.snapshot.assert_called_once()
        await evaluator.evaluate_and_execute(request.hook_name, ctx, request.event)
        assert provider.snapshot.call_count == 2
        assert len(broker.submitted) == 1
        await GraphEvaluator(graph).evaluate_and_execute(
            request.hook_name, ctx, request.event
        )
        assert len(broker.submitted) == 2

    asyncio.run(run())


def test_fractional_whole_number_error_identifies_setting():
    read = operation_result(
        operation_graph(GraphOperation.ROUND, dict(value=2, places=Decimal("2.7")))
    )
    value = read.outputs[GraphPort.VALUE]
    assert value.reason == GraphReason.WHOLE_NUMBER_REQUIRED
    assert value.input_handle_id == GraphPort.PLACES
    assert "Decimal places" in value.message


def test_broker_exception_reports_originating_node_before_failing():
    fixture = preview_fixture()
    request = GraphPreviewRequest(**fixture["request"])
    broker = AsyncMock()
    broker.submit.side_effect = RuntimeError("test broker unavailable")
    sink = AsyncMock()
    ctx = replace(context(portfolio=request.portfolio), broker=broker, activity=sink)
    with pytest.raises(RuntimeError, match="test broker unavailable"):
        asyncio.run(
            GraphEvaluator(request.graph).evaluate_and_execute(
                request.hook_name, ctx, request.event
            )
        )
    assert any(
        "[buy] Execution failed" in call.args[0] for call in sink.emit.await_args_list
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"token_id": ""},
        {"asks": [{"price": "0.4", "size": "0"}]},
        {"bids": [{"price": "0.6", "size": "1"}]},
        {"received_at_ms": -1},
    ],
)
def test_preview_rejects_semantically_invalid_books_at_ingress(mutation):
    payload = dict(
        token_id="token",
        bids=[dict(price="0.39", size="100")],
        asks=[dict(price="0.4", size="100")],
        received_at_ms=1000,
    )
    payload.update(mutation)
    with pytest.raises(ValueError):
        GraphPreviewRequest(
            graph=threshold_buy_graph(),
            hook_name="on_book",
            now_ms=1000,
            payload=payload,
        )


@pytest.mark.parametrize("invalid_input", ["wallet", "stale", "future"])
def test_preview_rejects_invalid_wallet_trade_at_ingress(invalid_input):
    trigger = next(
        item
        for item in GRAPH_NODE_CATALOG.triggers
        if item.hook_name == BaseBot.on_wallet_trade.__name__
    )
    payload = dict(trigger.sample_payload)
    now_ms = trigger.sample_time_ms
    if invalid_input == "wallet":
        payload["wallet"] = "malformed"
    elif invalid_input == "stale":
        now_ms = payload["trade_timestamp_ms"] + DEFAULT_EVENT_MAX_AGE_MS + 1
    else:
        payload["observed_at_ms"] = now_ms + 1
    expected_reason = {
        "wallet": "wallet address",
        "stale": WalletTradeValidationIssue.STALE.value,
        "future": WalletTradeValidationIssue.FUTURE_DATED.value,
    }[invalid_input]
    with pytest.raises(ValueError, match=expected_reason):
        GraphPreviewRequest(
            graph=dict(
                nodes=[
                    dict(
                        id="trigger",
                        type=GraphNodeType.TRIGGER,
                        position=dict(x=0, y=0),
                        data=dict(hook_name=trigger.hook_name),
                    )
                ]
            ),
            hook_name=trigger.hook_name,
            payload=payload,
            now_ms=now_ms,
        )


@pytest.mark.parametrize(
    "hook", [BaseBot.on_book.__name__, BaseBot.on_wallet_trade.__name__]
)
def test_preview_normalizes_external_identity_fields(hook):
    trigger = next(
        item for item in GRAPH_NODE_CATALOG.triggers if item.hook_name == hook
    )
    payload = dict(trigger.sample_payload)
    original_token = payload["token_id"]
    payload["token_id"] = f"  {original_token}  "
    if hook == BaseBot.on_wallet_trade.__name__:
        payload["wallet"] = "  0x" + "A" * 40 + "  "
    request = GraphPreviewRequest(
        graph=dict(
            nodes=[
                dict(
                    id="trigger",
                    type=GraphNodeType.TRIGGER,
                    position=dict(x=0, y=0),
                    data=dict(hook_name=hook),
                )
            ]
        ),
        hook_name=hook,
        payload=payload,
        now_ms=trigger.sample_time_ms,
    )
    assert request.event.token_id == original_token
    if hook == BaseBot.on_wallet_trade.__name__:
        assert request.event.wallet == "0x" + "a" * 40


@pytest.mark.parametrize(
    "invalid_port, invalid_value",
    [
        (GraphPort.KEY, RuntimeValue(" ")),
        (GraphPort.KEY, RuntimeValue.invalid(GraphReason.INVALID_KEY)),
        (GraphPort.DURATION_MS, RuntimeValue(Decimal("1.5"))),
    ],
)
@pytest.mark.parametrize("existing_claims", [False, True])
def test_invalid_control_inputs_do_not_create_or_expire_claims(
    invalid_port, invalid_value, existing_claims
):
    claims = {"node": {"expired": 1}} if existing_claims else {}
    state = EventControlState(claims=claims)
    inputs = {
        GraphPort.ENABLED: RuntimeValue(True),
        GraphPort.KEY: RuntimeValue("next"),
        GraphPort.DURATION_MS: RuntimeValue(Decimal(10)),
        invalid_port: invalid_value,
    }
    result = state.evaluate("node", GraphOperation.COOLDOWN, inputs, 100)
    assert not result.available
    assert state.claims == ({"node": {"expired": 1}} if existing_claims else {})


@pytest.mark.parametrize(
    "hook, field",
    [
        (BaseBot.on_wallet_trade.__name__, "condition_id"),
        (BaseBot.on_wallet_trade.__name__, "source_id"),
        (BaseBot.on_market_resolved.__name__, "condition_id"),
        (BaseBot.on_market_resolved.__name__, "market_slug"),
        (BaseBot.on_book_gap.__name__, "condition_id"),
    ],
)
def test_preview_rejects_blank_event_identifiers(hook, field):
    trigger = next(
        item for item in GRAPH_NODE_CATALOG.triggers if item.hook_name == hook
    )
    payload = {**trigger.sample_payload, field: "   "}
    graph = dict(
        nodes=[
            dict(
                id="trigger",
                type=GraphNodeType.TRIGGER,
                position=dict(x=0, y=0),
                data=dict(hook_name=hook),
            )
        ]
    )
    with pytest.raises(ValueError, match="nonempty"):
        GraphPreviewRequest(
            graph=graph, hook_name=hook, payload=payload, now_ms=trigger.sample_time_ms
        )


@pytest.mark.parametrize("price", ["0", "-0.1", "1.1"])
def test_preview_rejects_out_of_range_average_entry_prices(price):
    with pytest.raises(ValueError, match="average entry price"):
        PreviewPortfolio(
            positions=[dict(token_id="token", size="1", average_entry_price=price)]
        )


def test_preview_normalizes_portfolio_token_ids_and_rejects_duplicate_or_blank_ids():
    position = dict(token_id=" token ", size="1", average_entry_price="0.4")
    assert (
        PreviewPortfolio(positions=[position]).snapshot().positions[0].token_id
        == "token"
    )
    with pytest.raises(ValueError, match="unique"):
        PreviewPortfolio(positions=[position, {**position, "token_id": "token"}])
    with pytest.raises(ValueError, match="nonempty"):
        PreviewPortfolio(positions=[{**position, "token_id": "   "}])
