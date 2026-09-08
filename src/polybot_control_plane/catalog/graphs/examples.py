"""Executable, configurable example graphs built from the current contract."""

from pydantic import BaseModel
from polybot_control_plane.catalog.graphs.contracts import NodeGraph
from polybot_control_plane.catalog.graphs.values import (
    GraphPort,
    GraphOperation,
    GraphScalarType,
    GraphComparisonOperator,
    GraphBrokerAction,
)


class GraphExample(BaseModel):
    name: str
    description: str
    graph: NodeGraph


class _ExampleBuilder:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.parameters: list[dict] = []
        self.node("book", "trigger", {"hook_name": "on_book"})

    def node(self, id: str, type: str, data: dict) -> None:
        index = len(self.nodes)
        self.nodes.append(
            dict(
                id=id,
                type=type,
                position=dict(x=(index % 5) * 320, y=(index // 5) * 260),
                data=data,
            )
        )

    def connect(self, source: str, output: str, target: str, input: str) -> None:
        self.edges.append(
            dict(
                id=f"{source}-{output}-{target}-{input}",
                source=source,
                source_handle=output,
                target=target,
                target_handle=input,
            )
        )

    def operation(
        self, id: str, operation: GraphOperation, **inputs: tuple[str, str]
    ) -> None:
        self.node(id, "operation", dict(operation=operation))
        for name, (source, output) in inputs.items():
            self.connect(source, output, id, name)

    def parameter(self, id: str, name: str, value: str) -> None:
        self.parameters.append(
            dict(
                id=id,
                name=name,
                data=dict(scalar_type=GraphScalarType.NUMBER, value=value),
            )
        )
        self.node(id, "parameter", dict(parameter_id=id))

    def comparison(
        self,
        id: str,
        operator: GraphComparisonOperator,
        left: tuple[str, str],
        right: tuple[str, str],
    ) -> None:
        self.node(id, "comparison", dict(operator=operator))
        self.connect(*left, id, GraphPort.LEFT)
        self.connect(*right, id, GraphPort.RIGHT)

    def action(
        self,
        id: str,
        action: GraphBrokerAction,
        enabled: tuple[str, str],
        price: str,
        size: tuple[str, str],
    ) -> None:
        self.node(id, "broker_action", dict(action=action))
        self.connect(*enabled, id, GraphPort.ENABLED)
        self.connect("book", "field:token_id", id, GraphPort.TOKEN_ID)
        self.connect("book", price, id, "price")
        self.connect(*size, id, GraphPort.SIZE)

    def graph(self) -> NodeGraph:
        return NodeGraph.model_validate(
            dict(nodes=self.nodes, edges=self.edges, parameters=self.parameters)
        )


def entry_exit_example() -> GraphExample:
    builder = _ExampleBuilder()
    builder.parameter("entry", "Entry threshold", "0.45")
    builder.parameter("exit", "Exit threshold", "0.60")
    builder.parameter("budget", "Budget", "1")
    builder.operation(
        "position",
        GraphOperation.POSITION,
        context=("book", GraphPort.CONTEXT),
        token_id=("book", "field:token_id"),
    )
    builder.operation(
        "flat", GraphOperation.NOT, value=("position", GraphPort.HAS_POSITION)
    )
    builder.comparison(
        "cheap",
        GraphComparisonOperator.LESS_THAN_OR_EQUAL,
        ("book", "field:best_ask.price"),
        ("entry", GraphPort.VALUE),
    )
    builder.operation(
        "enter",
        GraphOperation.AND,
        input_1=("flat", GraphPort.RESULT),
        input_2=("cheap", GraphPort.RESULT),
    )
    builder.operation(
        "shares",
        GraphOperation.DIVIDE,
        left=("budget", GraphPort.VALUE),
        right=("book", "field:best_ask.price"),
    )
    builder.action(
        "buy",
        GraphBrokerAction.SUBMIT_BUY,
        ("enter", GraphPort.RESULT),
        "field:best_ask.price",
        ("shares", GraphPort.VALUE),
    )
    builder.comparison(
        "expensive",
        GraphComparisonOperator.GREATER_THAN_OR_EQUAL,
        ("book", "field:best_bid.price"),
        ("exit", GraphPort.VALUE),
    )
    builder.operation(
        "leave",
        GraphOperation.AND,
        input_1=("position", GraphPort.HAS_POSITION),
        input_2=("expensive", GraphPort.RESULT),
    )
    builder.action(
        "sell",
        GraphBrokerAction.SUBMIT_SELL,
        ("leave", GraphPort.RESULT),
        "field:best_bid.price",
        ("position", GraphPort.SIZE),
    )
    return GraphExample(
        name="Threshold entry and exit",
        description="Buy while flat below the entry threshold; sell the held position above the exit threshold. Budget is expressed in paper cash.",
        graph=builder.graph(),
    )


def multiple_conditions_example() -> GraphExample:
    builder = _ExampleBuilder()
    builder.parameter("entry", "Entry threshold", "0.45")
    builder.parameter("budget", "Budget", "1")
    builder.parameter("cooldown_ms", "Cooldown milliseconds", "1000")
    builder.operation(
        "cash", GraphOperation.BALANCE, context=("book", GraphPort.CONTEXT)
    )
    builder.operation(
        "position",
        GraphOperation.POSITION,
        context=("book", GraphPort.CONTEXT),
        token_id=("book", "field:token_id"),
    )
    builder.operation(
        "flat", GraphOperation.NOT, value=("position", GraphPort.HAS_POSITION)
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
        ("book", "field:best_ask.price"),
        ("entry", GraphPort.VALUE),
    )
    builder.operation(
        "conditions",
        GraphOperation.AND,
        input_1=("flat", GraphPort.RESULT),
        input_2=("cheap", GraphPort.RESULT),
        input_3=("funded", GraphPort.RESULT),
    )
    next(node for node in builder.nodes if node["id"] == "conditions")["data"][
        "input_ids"
    ] = ["input_1", "input_2", "input_3"]
    builder.operation(
        "gate",
        GraphOperation.COOLDOWN,
        context=("book", GraphPort.CONTEXT),
        enabled=("conditions", GraphPort.RESULT),
        key=("book", "field:token_id"),
        duration_ms=("cooldown_ms", GraphPort.VALUE),
    )
    builder.operation(
        "shares",
        GraphOperation.DIVIDE,
        left=("budget", GraphPort.VALUE),
        right=("book", "field:best_ask.price"),
    )
    builder.action(
        "buy",
        GraphBrokerAction.SUBMIT_BUY,
        ("gate", GraphPort.RESULT),
        "field:best_ask.price",
        ("shares", GraphPort.VALUE),
    )
    builder.operation(
        "explain",
        GraphOperation.LOG,
        context=("book", GraphPort.CONTEXT),
        value=("buy", GraphPort.STATUS),
    )
    return GraphExample(
        name="Multiple conditions and cooldown",
        description="Require a flat position, a cheap ask, sufficient cash, and a per-token cooldown; log the order outcome.",
        graph=builder.graph(),
    )


GRAPH_EXAMPLES = (entry_exit_example(), multiple_conditions_example())
