"""Validated public node and edge contracts for alpha graphs."""

from __future__ import annotations

from collections import defaultdict, deque
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
from polybot_control_plane.catalog.graphs.types import (
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_VALUE_HANDLE_ID,
    GraphBrokerAction,
    GraphComparisonOperator,
    GraphCoordinate,
    GraphElementId,
    GraphHookName,
    GraphNodeType,
    GraphScalarType,
)


MAX_NODE_GRAPH_NODES = 50
MAX_NODE_GRAPH_EDGES = 200


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

    id: GraphElementId
    source: GraphElementId
    source_handle: GraphElementId
    target: GraphElementId
    target_handle: GraphElementId


class _ResolvedOutput:
    def __init__(self, scalar_type: GraphScalarType, nullable: bool) -> None:
        self.scalar_type = scalar_type
        self.nullable = nullable


class NodeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    nodes: tuple[GraphNode, ...] = Field(min_length=1, max_length=MAX_NODE_GRAPH_NODES)
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
        incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in self.edges:
            source = nodes_by_id.get(edge.source)
            target = nodes_by_id.get(edge.target)
            if source is None or target is None:
                raise ValueError("graph edges must reference existing nodes")
            output = self._resolve_output(source, edge.source_handle)
            expected_input = self._resolve_input(target, edge.target_handle)
            if output.scalar_type not in expected_input.scalar_types:
                raise ValueError("graph edge scalar types are incompatible")
            incoming[target.id].append(edge)
            outgoing[source.id].append(edge)

        for node in self.nodes:
            expected_inputs = self._inputs(node)
            incoming_edge_counts_by_handle: dict[str, int] = defaultdict(int)
            for edge in incoming[node.id]:
                incoming_edge_counts_by_handle[edge.target_handle] += 1
            for input_ in expected_inputs:
                count = incoming_edge_counts_by_handle[input_.handle_id]
                if count > 1 or (input_.required and count != 1):
                    raise ValueError("graph input cardinality is invalid")

        order = self._topological_order(incoming, outgoing)
        trigger_ancestors = self._trigger_ancestors(order, nodes_by_id, incoming)
        for node_id in order:
            node = nodes_by_id[node_id]
            if isinstance(node, GraphComparisonNode):
                self._validate_comparison_inputs(incoming[node_id], nodes_by_id)

        descendant_actions = self._descendant_actions(
            order,
            nodes_by_id,
            outgoing,
        )
        for node in self.nodes:
            if isinstance(node, GraphTriggerNode):
                continue
            actions = descendant_actions[node.id]
            branch_triggers = self._trigger_ids_for_actions(
                actions,
                trigger_ancestors,
            )
            if not actions or len(branch_triggers) != 1:
                raise ValueError(
                    "graph processing and action nodes must belong to one trigger branch"
                )
        return self

    @staticmethod
    def _trigger_ancestors(
        order: tuple[str, ...],
        nodes_by_id: dict[str, GraphNode],
        incoming: dict[str, list[GraphEdge]],
    ) -> dict[str, frozenset[str]]:
        trigger_ancestors_by_node: dict[str, frozenset[str]] = {}
        for node_id in order:
            trigger_ancestors_by_node[node_id] = (
                frozenset({node_id})
                if isinstance(nodes_by_id[node_id], GraphTriggerNode)
                else frozenset().union(
                    *(
                        trigger_ancestors_by_node[edge.source]
                        for edge in incoming[node_id]
                    )
                )
            )
        return trigger_ancestors_by_node

    @staticmethod
    def _descendant_actions(
        order: tuple[str, ...],
        nodes_by_id: dict[str, GraphNode],
        outgoing: dict[str, list[GraphEdge]],
    ) -> dict[str, frozenset[str]]:
        descendant_actions_by_node: dict[str, frozenset[str]] = {}
        for node_id in reversed(order):
            descendant_actions_by_node[node_id] = (
                frozenset({node_id})
                if isinstance(nodes_by_id[node_id], GraphBrokerActionNode)
                else frozenset().union(
                    *(
                        descendant_actions_by_node[edge.target]
                        for edge in outgoing[node_id]
                    )
                )
            )
        return descendant_actions_by_node

    @staticmethod
    def _trigger_ids_for_actions(
        action_ids: frozenset[str],
        trigger_ancestors: dict[str, frozenset[str]],
    ) -> frozenset[str]:
        return frozenset().union(
            *(trigger_ancestors[action_id] for action_id in action_ids)
        )

    def _resolve_output(self, node: GraphNode, handle_id: str) -> _ResolvedOutput:
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
        handle_id: str,
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

    def _topological_order(
        self,
        incoming: dict[str, list[GraphEdge]],
        outgoing: dict[str, list[GraphEdge]],
    ) -> tuple[str, ...]:
        remaining_incoming_edges = {
            node.id: len(incoming[node.id]) for node in self.nodes
        }
        ready = deque(
            node.id for node in self.nodes if remaining_incoming_edges[node.id] == 0
        )
        order: list[str] = []
        while ready:
            node_id = ready.popleft()
            order.append(node_id)
            for edge in outgoing[node_id]:
                remaining_incoming_edges[edge.target] -= 1
                if remaining_incoming_edges[edge.target] == 0:
                    ready.append(edge.target)
        if len(order) != len(self.nodes):
            raise ValueError("graph must be acyclic")
        return tuple(order)
