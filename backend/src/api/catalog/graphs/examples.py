"""Executable, configurable example graphs built from the current contract."""

from polybot.framework.base import BaseBot
from pydantic import BaseModel

from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.operations import DEFAULT_BOOLEAN_INPUT_IDS
from api.catalog.graphs.types import GraphFieldPath
from api.catalog.graphs.values import (
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)

FUNDING_CONDITION_INPUT = "input_3"

BUDGET_LABEL = "Budget"


ENTRY_THRESHOLD_LABEL = "Entry threshold"


class GraphExample(BaseModel):
    name: str
    description: str
    graph: NodeGraph


class _ExampleBuilder:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.parameters: list[dict] = []
        self.node(
            "book", GraphNodeType.TRIGGER, {"hook_name": BaseBot.on_book.__name__}
        )

    def node(self, node_id: str, node_type: str, node_data: dict) -> None:
        index = len(self.nodes)
        self.nodes.append(
            dict(
                id=node_id,
                type=node_type,
                position=dict(x=(index % 5) * 320, y=(index // 5) * 260),
                data=node_data,
            )
        )

    def connect(
        self,
        source_node_id: str,
        source_handle_id: str,
        target_node_id: str,
        target_handle_id: str,
    ) -> None:
        self.edges.append(
            dict(
                id=f"{source_node_id}-{source_handle_id}-{target_node_id}-{target_handle_id}",
                source=source_node_id,
                source_handle=source_handle_id,
                target=target_node_id,
                target_handle=target_handle_id,
            )
        )

    def operation(
        self,
        node_id: str,
        operation: GraphOperation,
        inputs: dict[str, tuple[str, str]],
    ) -> None:
        self.node(node_id, GraphNodeType.OPERATION, dict(operation=operation))
        for name, (source_node_id, source_handle_id) in inputs.items():
            self.connect(source_node_id, source_handle_id, node_id, name)

    def parameter(self, node_id: str, name: str, value: str) -> None:
        self.parameters.append(
            dict(
                id=node_id,
                name=name,
                data=dict(scalar_type=GraphScalarType.NUMBER, value=value),
            )
        )
        self.node(node_id, GraphNodeType.PARAMETER, dict(parameter_id=node_id))

    def comparison(
        self,
        node_id: str,
        operator: GraphComparisonOperator,
        left: tuple[str, str],
        right: tuple[str, str],
    ) -> None:
        self.node(node_id, GraphNodeType.COMPARISON, dict(operator=operator))
        self.connect(*left, node_id, GraphPort.LEFT)
        self.connect(*right, node_id, GraphPort.RIGHT)

    def action(
        self,
        node_id: str,
        action: GraphBrokerAction,
        enabled: tuple[str, str],
        price: str,
        size: tuple[str, str],
    ) -> None:
        self.node(node_id, GraphNodeType.BROKER_ACTION, dict(action=action))
        self.connect(*enabled, node_id, GraphPort.ENABLED)
        self.connect(
            "book",
            GraphFieldPath(segments=("token_id",)).handle_id,
            node_id,
            GraphPort.TOKEN_ID,
        )
        self.connect("book", price, node_id, GraphPort.PRICE)
        self.connect(*size, node_id, GraphPort.SIZE)

    def graph(self) -> NodeGraph:
        return NodeGraph.model_validate(
            dict(nodes=self.nodes, edges=self.edges, parameters=self.parameters)
        )


def entry_exit_example() -> GraphExample:
    builder = _ExampleBuilder()
    builder.parameter("entry", ENTRY_THRESHOLD_LABEL, "0.45")
    builder.parameter("exit", "Exit threshold", "0.60")
    builder.parameter("budget", BUDGET_LABEL, "1")
    builder.operation(
        "position",
        GraphOperation.POSITION,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.TOKEN_ID: (
                "book",
                GraphFieldPath(segments=("token_id",)).handle_id,
            ),
        },
    )
    builder.operation(
        "flat",
        GraphOperation.NOT,
        {GraphPort.VALUE: ("position", GraphPort.HAS_POSITION)},
    )
    builder.comparison(
        "cheap",
        GraphComparisonOperator.LESS_THAN_OR_EQUAL,
        ("book", GraphFieldPath(segments=("best_ask", "price")).handle_id),
        ("entry", GraphPort.VALUE),
    )
    builder.operation(
        "enter",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("flat", GraphPort.RESULT),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("cheap", GraphPort.RESULT),
        },
    )
    builder.operation(
        "shares",
        GraphOperation.DIVIDE,
        {
            GraphPort.LEFT: ("budget", GraphPort.VALUE),
            GraphPort.RIGHT: (
                "book",
                GraphFieldPath(segments=("best_ask", "price")).handle_id,
            ),
        },
    )
    builder.action(
        "buy",
        GraphBrokerAction.SUBMIT_BUY,
        ("enter", GraphPort.RESULT),
        GraphFieldPath(segments=("best_ask", "price")).handle_id,
        ("shares", GraphPort.VALUE),
    )
    builder.comparison(
        "expensive",
        GraphComparisonOperator.GREATER_THAN_OR_EQUAL,
        ("book", GraphFieldPath(segments=("best_bid", "price")).handle_id),
        ("exit", GraphPort.VALUE),
    )
    builder.operation(
        "leave",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("position", GraphPort.HAS_POSITION),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("expensive", GraphPort.RESULT),
        },
    )
    builder.action(
        "sell",
        GraphBrokerAction.SUBMIT_SELL,
        ("leave", GraphPort.RESULT),
        GraphFieldPath(segments=("best_bid", "price")).handle_id,
        ("position", GraphPort.SIZE),
    )
    return GraphExample(
        name="Threshold entry and exit",
        description="Buy while flat below the entry threshold; sell the held position above the exit threshold. Budget is expressed in paper cash.",
        graph=builder.graph(),
    )


def multiple_conditions_example() -> GraphExample:
    builder = _ExampleBuilder()
    builder.parameter("entry", ENTRY_THRESHOLD_LABEL, "0.45")
    builder.parameter("budget", BUDGET_LABEL, "1")
    builder.parameter("cooldown_ms", "Cooldown milliseconds", "1000")
    builder.operation(
        "cash", GraphOperation.BALANCE, {GraphPort.CONTEXT: ("book", GraphPort.CONTEXT)}
    )
    builder.operation(
        "position",
        GraphOperation.POSITION,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.TOKEN_ID: (
                "book",
                GraphFieldPath(segments=("token_id",)).handle_id,
            ),
        },
    )
    builder.operation(
        "flat",
        GraphOperation.NOT,
        {GraphPort.VALUE: ("position", GraphPort.HAS_POSITION)},
    )
    builder.comparison(
        "funded",
        GraphComparisonOperator.GREATER_THAN_OR_EQUAL,
        ("cash", GraphPort.AVAILABLE_CASH),
        ("budget", GraphPort.VALUE),
    )
    builder.comparison(
        "cheap",
        GraphComparisonOperator.LESS_THAN_OR_EQUAL,
        ("book", GraphFieldPath(segments=("best_ask", "price")).handle_id),
        ("entry", GraphPort.VALUE),
    )
    builder.operation(
        "conditions",
        GraphOperation.AND,
        {
            DEFAULT_BOOLEAN_INPUT_IDS[0]: ("flat", GraphPort.RESULT),
            DEFAULT_BOOLEAN_INPUT_IDS[1]: ("cheap", GraphPort.RESULT),
            FUNDING_CONDITION_INPUT: ("funded", GraphPort.RESULT),
        },
    )
    next(node for node in builder.nodes if node["id"] == "conditions")["data"][
        "input_ids"
    ] = [*DEFAULT_BOOLEAN_INPUT_IDS, FUNDING_CONDITION_INPUT]
    builder.operation(
        "gate",
        GraphOperation.COOLDOWN,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.ENABLED: ("conditions", GraphPort.RESULT),
            GraphPort.KEY: ("book", GraphFieldPath(segments=("token_id",)).handle_id),
            GraphPort.DURATION_MS: ("cooldown_ms", GraphPort.VALUE),
        },
    )
    builder.operation(
        "shares",
        GraphOperation.DIVIDE,
        {
            GraphPort.LEFT: ("budget", GraphPort.VALUE),
            GraphPort.RIGHT: (
                "book",
                GraphFieldPath(segments=("best_ask", "price")).handle_id,
            ),
        },
    )
    builder.action(
        "buy",
        GraphBrokerAction.SUBMIT_BUY,
        ("gate", GraphPort.RESULT),
        GraphFieldPath(segments=("best_ask", "price")).handle_id,
        ("shares", GraphPort.VALUE),
    )
    builder.operation(
        "explain",
        GraphOperation.LOG,
        {
            GraphPort.CONTEXT: ("book", GraphPort.CONTEXT),
            GraphPort.VALUE: ("buy", GraphPort.STATUS),
        },
    )
    return GraphExample(
        name="Multiple conditions and cooldown",
        description="Require a flat position, a cheap ask, sufficient cash, and a per-token cooldown; log the order outcome.",
        graph=builder.graph(),
    )


GRAPH_EXAMPLES = (entry_exit_example(), multiple_conditions_example())
