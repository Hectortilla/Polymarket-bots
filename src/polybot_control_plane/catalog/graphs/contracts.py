"""Validated public node and edge contracts for alpha graphs."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from polybot_control_plane.catalog.graphs._validation import (
    ensure_unique_graph_trigger_hooks,
    ensure_unique_values,
)
from polybot_control_plane.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphInputDescriptor,
    GraphNodeCatalog,
)
from polybot_control_plane.catalog.graphs.topology import GraphTopology
from polybot_control_plane.catalog.graphs.values import (
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphNodeType,
    GraphScalarType,
)
from polybot_control_plane.catalog.graphs.types import (
    GraphCoordinate,
    GraphEdgeId,
    GraphElementId,
    GraphHookName,
    GraphHandleId,
)

MIN_NODE_GRAPH_NODES = 1
MAX_NODE_GRAPH_NODES = 50
MAX_NODE_GRAPH_EDGES = 200
MAX_INPUT_CONNECTIONS_PER_HANDLE = 1
NO_INPUT_CONNECTIONS = 0
EXPECTED_TRIGGER_BRANCH_COUNT = 1


class GraphPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: GraphCoordinate
    y: GraphCoordinate


class GraphTriggerNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    hook_name: GraphHookName

    @model_validator(mode="after")
    def _validate_hook(self) -> Self:
        if self.catalog.trigger(self.hook_name) is None:
            raise ValueError("graph trigger hook is not supported")
        return self


class GraphBooleanConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.BOOLEAN]
    value: StrictBool


class GraphIntegerConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.INTEGER]
    value: StrictInt


class GraphDecimalConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.DECIMAL]
    value: StrictStr

    @field_validator("value")
    @classmethod
    def _validate_decimal(cls, value: str) -> str:
        try:
            if not Decimal(value).is_finite():
                raise ValueError
        except (InvalidOperation, ValueError) as error:
            raise ValueError(
                "decimal graph constants must be finite decimal strings"
            ) from error
        return value


class GraphStringConstantData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scalar_type: Literal[GraphScalarType.STRING]
    value: StrictStr


type GraphConstantNodeData = Annotated[
    GraphBooleanConstantData
    | GraphIntegerConstantData
    | GraphDecimalConstantData
    | GraphStringConstantData,
    Field(discriminator="scalar_type"),
]


class GraphComparisonNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operator: GraphComparisonOperator


class GraphBrokerActionNodeData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: GraphBrokerAction


class GraphTriggerNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.TRIGGER]
    position: GraphPosition
    data: GraphTriggerNodeData


class GraphConstantNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.CONSTANT]
    position: GraphPosition
    data: GraphConstantNodeData

    def runtime_value(self) -> object:
        return (
            Decimal(self.data.value)
            if self.data.scalar_type is GraphScalarType.DECIMAL
            else self.data.value
        )


class GraphComparisonNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.COMPARISON]
    position: GraphPosition
    data: GraphComparisonNodeData


class GraphBrokerActionNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphElementId
    type: Literal[GraphNodeType.BROKER_ACTION]
    position: GraphPosition
    data: GraphBrokerActionNodeData


type GraphNode = Annotated[
    GraphTriggerNode | GraphConstantNode | GraphComparisonNode | GraphBrokerActionNode,
    Field(discriminator="type"),
]


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: GraphEdgeId
    source: GraphElementId
    source_handle: GraphHandleId
    target: GraphElementId
    target_handle: GraphHandleId


class _ResolvedOutput:
    def __init__(self, scalar_type: GraphScalarType, nullable: bool) -> None:
        self.scalar_type = scalar_type
        self.nullable = nullable


class NodeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    nodes: tuple[GraphNode, ...] = Field(
        min_length=MIN_NODE_GRAPH_NODES,
        max_length=MAX_NODE_GRAPH_NODES,
    )
    edges: tuple[GraphEdge, ...] = Field(default=(), max_length=MAX_NODE_GRAPH_EDGES)

    @model_validator(mode="after")
    def _validate_graph(self) -> Self:
        ensure_unique_values(tuple(node.id for node in self.nodes), "graph node ID")
        ensure_unique_values(tuple(edge.id for edge in self.edges), "graph edge ID")
        triggers = tuple(
            node for node in self.nodes if isinstance(node, GraphTriggerNode)
        )
        ensure_unique_graph_trigger_hooks(
            tuple(node.data.hook_name for node in triggers),
        )

        nodes_by_id = {node.id: node for node in self.nodes}
        for edge in self.edges:
            source = nodes_by_id.get(edge.source)
            target = nodes_by_id.get(edge.target)
            if source is None or target is None:
                raise ValueError("graph edges must reference existing nodes")
            output = self._resolve_output(source, edge.source_handle)
            expected_input = self._resolve_input(target, edge.target_handle)
            if output.scalar_type not in expected_input.scalar_types:
                raise ValueError("graph edge scalar types are incompatible")

        topology = GraphTopology.from_edges(nodes_by_id, self.edges)
        incoming = topology.incoming

        for node in self.nodes:
            expected_inputs = self._inputs(node)
            incoming_edge_counts_by_handle: dict[str, int] = defaultdict(int)
            for edge in incoming[node.id]:
                incoming_edge_counts_by_handle[edge.target_handle] += 1
            for input_ in expected_inputs:
                count = incoming_edge_counts_by_handle[input_.handle_id]
                node_name = self._node_display_name(node)
                if count > MAX_INPUT_CONNECTIONS_PER_HANDLE:
                    raise ValueError(
                        f"the {node_name} {input_.display_name} input accepts "
                        "only one connection"
                    )
                if input_.required and count == NO_INPUT_CONNECTIONS:
                    raise ValueError(
                        f"connect the required {input_.display_name} input on "
                        f"the {node_name}"
                    )

        for node_id in topology.topological_order:
            node = nodes_by_id[node_id]
            if isinstance(node, GraphComparisonNode):
                self._validate_comparison_inputs(incoming[node_id], nodes_by_id)

        trigger_ids = frozenset(node.id for node in triggers)
        action_ids = frozenset(
            node.id for node in self.nodes if isinstance(node, GraphBrokerActionNode)
        )
        # Every processing node must contribute to an action owned by exactly
        # one trigger; otherwise runtime branch compilation could join events.
        for node in self.nodes:
            if isinstance(node, GraphTriggerNode):
                continue
            descendant_action_ids = topology.descendant_ids[node.id] & action_ids
            branch_trigger_ids = frozenset().union(
                *(
                    topology.ancestor_ids[action_id] & trigger_ids
                    for action_id in descendant_action_ids
                )
            )
            if (
                not descendant_action_ids
                or len(branch_trigger_ids) != EXPECTED_TRIGGER_BRANCH_COUNT
            ):
                raise ValueError(
                    "graph processing and action nodes must belong to one "
                    "trigger branch"
                )
        return self

    def _resolve_output(
        self,
        node: GraphNode,
        handle_id: GraphHandleId,
    ) -> _ResolvedOutput:
        if isinstance(node, GraphTriggerNode):
            trigger = self.catalog.trigger(node.data.hook_name)
            if trigger is None or trigger.payload is None:
                raise ValueError("graph source handle does not exist")
            field = next(
                (
                    candidate
                    for candidate in trigger.payload.fields
                    if candidate.handle_id == handle_id
                ),
                None,
            )
            if field is None or field.scalar_type is None:
                raise ValueError("graph source handle must be a scalar trigger output")
            return _ResolvedOutput(field.scalar_type, field.nullable)
        if isinstance(node, GraphConstantNode) and handle_id == GRAPH_VALUE_HANDLE_ID:
            output = self.catalog.constant(node.data.scalar_type).output
            return _ResolvedOutput(output.scalar_type, output.nullable)
        if (
            isinstance(node, GraphComparisonNode)
            and handle_id == GRAPH_COMPARISON_RESULT_HANDLE_ID
        ):
            output = self.catalog.comparison(node.data.operator).output
            return _ResolvedOutput(output.scalar_type, output.nullable)
        raise ValueError("graph source handle does not exist")

    def _resolve_input(
        self,
        node: GraphNode,
        handle_id: GraphHandleId,
    ) -> GraphInputDescriptor:
        input_ = next(
            (input_ for input_ in self._inputs(node) if input_.handle_id == handle_id),
            None,
        )
        if input_ is None:
            raise ValueError("graph target handle does not exist")
        return input_

    def _inputs(self, node: GraphNode) -> tuple[GraphInputDescriptor, ...]:
        if isinstance(node, GraphComparisonNode):
            return self.catalog.comparison(node.data.operator).inputs
        if isinstance(node, GraphBrokerActionNode):
            return self.catalog.broker_action(node.data.action).inputs
        return ()

    def _node_display_name(self, node: GraphNode) -> str:
        if isinstance(node, GraphComparisonNode):
            comparison = self.catalog.comparison(node.data.operator)
            return f"{comparison.display_name} comparison"
        if isinstance(node, GraphBrokerActionNode):
            return self.catalog.broker_action(node.data.action).display_name
        if isinstance(node, GraphTriggerNode):
            return f"{node.data.hook_name} trigger"
        return self.catalog.constant(node.data.scalar_type).display_name

    def _validate_comparison_inputs(
        self,
        edges: list[GraphEdge],
        nodes_by_id: dict[str, GraphNode],
    ) -> None:
        source_scalar_types_by_handle = {
            edge.target_handle: self._resolve_output(
                nodes_by_id[edge.source], edge.source_handle
            ).scalar_type
            for edge in edges
        }
        if (
            len(source_scalar_types_by_handle) == 2
            and len(set(source_scalar_types_by_handle.values())) != 1
        ):
            raise ValueError("graph comparisons require matching scalar input types")
