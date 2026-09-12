from polybot.framework.base import BaseBot

from api.catalog.graphs.book_paths import (
    BOOK_TOKEN_ID_PATH,
)
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.values import (
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphOperation,
    GraphPort,
    GraphScalarType,
)


class ExampleBuilder:
    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.parameters: list[dict] = []
        self.node(
            "book", GraphNodeType.TRIGGER, {"hook_name": BaseBot.on_book.__name__}
        )

    def node(self, node_id: str, node_type: GraphNodeType, node_data: dict) -> None:
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
        for target_input_handle_id, (
            source_node_id,
            source_handle_id,
        ) in inputs.items():
            self.connect(
                source_node_id, source_handle_id, node_id, target_input_handle_id
            )

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
        enabled_source_ref: tuple[str, str],
        price_source_handle_id: str,
        size_source_ref: tuple[str, str],
    ) -> None:
        self.node(node_id, GraphNodeType.BROKER_ACTION, dict(action=action))
        self.connect(*enabled_source_ref, node_id, GraphPort.ENABLED)
        self.connect(
            "book",
            BOOK_TOKEN_ID_PATH.handle_id,
            node_id,
            GraphPort.TOKEN_ID,
        )
        self.connect("book", price_source_handle_id, node_id, GraphPort.PRICE)
        self.connect(*size_source_ref, node_id, GraphPort.SIZE)

    def graph(self) -> NodeGraph:
        return NodeGraph.model_validate(
            dict(nodes=self.nodes, edges=self.edges, parameters=self.parameters)
        )
