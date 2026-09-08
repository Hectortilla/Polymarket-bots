from __future__ import annotations

from collections import defaultdict
from typing import ClassVar, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from api.catalog.graphs._validation import (
    ensure_unique_graph_trigger_hooks,
    ensure_unique_values,
)
from api.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphNodeCatalog,
)
from api.catalog.graphs.contracts.edges import GraphEdge
from api.catalog.graphs.contracts.limits import (
    EXPECTED_TRIGGER_BRANCH_COUNT,
    MAX_GRAPH_PARAMETERS,
    MAX_INPUT_CONNECTIONS_PER_HANDLE,
    MAX_NODE_GRAPH_EDGES,
    MAX_NODE_GRAPH_NODES,
    MIN_NODE_GRAPH_NODES,
    NO_INPUT_CONNECTIONS,
)
from api.catalog.graphs.contracts.nodes import (
    GraphBrokerActionNode,
    GraphComparisonNode,
    GraphConstantNode,
    GraphNode,
    GraphOperationNode,
    GraphParameter,
    GraphParameterNode,
    GraphTriggerNode,
)
from api.catalog.graphs.operations import (
    OPERATION_DESCRIPTORS,
)
from api.catalog.graphs.ports import (
    GraphInputDescriptor,
    GraphOutputDescriptor,
)
from api.catalog.graphs.topology import GraphTopology
from api.catalog.graphs.types import (
    GraphHandleId,
)
from api.catalog.graphs.values import (
    GRAPH_COMPARISON_RESULT_HANDLE_ID,
    GRAPH_CONTEXT_PORT_TYPE,
    GRAPH_VALUE_HANDLE_ID,
    GraphScalarType,
)

MISSING_SOURCE_HANDLE_MESSAGE = "graph source handle does not exist"


class NodeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog: ClassVar[GraphNodeCatalog] = GRAPH_NODE_CATALOG

    parameters: tuple[GraphParameter, ...] = Field(
        default=(), max_length=MAX_GRAPH_PARAMETERS, exclude_if=lambda value: not value
    )
    nodes: tuple[GraphNode, ...] = Field(
        min_length=MIN_NODE_GRAPH_NODES,
        max_length=MAX_NODE_GRAPH_NODES,
    )
    edges: tuple[GraphEdge, ...] = Field(default=(), max_length=MAX_NODE_GRAPH_EDGES)

    @model_validator(mode="after")
    def _validate_graph(self) -> Self:
        ensure_unique_values(tuple(p.id for p in self.parameters), "parameter ID")
        ensure_unique_values(tuple(p.name for p in self.parameters), "parameter name")
        parameter_ids = {p.id for p in self.parameters}
        for node in self.nodes:
            if (
                isinstance(node, GraphParameterNode)
                and node.data.parameter_id not in parameter_ids
            ):
                raise ValueError("parameter reference does not exist")
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
        terminal_ids = frozenset(
            node.id
            for node in self.nodes
            if isinstance(node, GraphBrokerActionNode)
            or isinstance(node, GraphOperationNode)
            and OPERATION_DESCRIPTORS[node.data.operation].terminal
        )
        for node in self.nodes:
            if isinstance(node, GraphTriggerNode):
                continue
            terminals = topology.descendant_ids[node.id] & terminal_ids
            if not terminals:
                raise ValueError(
                    "graph processing nodes must lead to an action or diagnostic in one trigger branch"
                )
            branch_triggers = frozenset().union(
                *(topology.ancestor_ids[end] & trigger_ids for end in terminals)
            )
            if isinstance(node, (GraphConstantNode, GraphParameterNode)):
                continue
            if len(branch_triggers) != EXPECTED_TRIGGER_BRANCH_COUNT:
                raise ValueError(
                    "graph processing and action nodes must belong to one trigger branch"
                )
        return self

    def _resolve_output(
        self,
        node: GraphNode,
        handle_id: GraphHandleId,
    ) -> _ResolvedOutput:
        if isinstance(node, GraphTriggerNode):
            trigger = self.catalog.trigger(node.data.hook_name)
            if trigger is not None and handle_id == trigger.context_handle_id:
                return _ResolvedOutput(GRAPH_CONTEXT_PORT_TYPE, False)
            if trigger is None or trigger.payload is None:
                raise ValueError(MISSING_SOURCE_HANDLE_MESSAGE)
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
        if isinstance(node, GraphParameterNode):
            parameter = next(
                p for p in self.parameters if p.id == node.data.parameter_id
            )
            if handle_id == GRAPH_VALUE_HANDLE_ID:
                return _ResolvedOutput(parameter.data.scalar_type, False)
        outputs = self._outputs(node)
        for port in outputs:
            if port.handle_id == handle_id:
                return _ResolvedOutput(port.scalar_type, port.nullable)
        raise ValueError(MISSING_SOURCE_HANDLE_MESSAGE)

    def _outputs(self, node: GraphNode) -> tuple[GraphOutputDescriptor, ...]:
        if isinstance(node, GraphOperationNode):
            return node.outputs()
        if isinstance(node, GraphBrokerActionNode):
            return self.catalog.broker_action(node.data.action).outputs
        return ()

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
        if isinstance(node, GraphOperationNode):
            return node.inputs()
        if isinstance(node, GraphComparisonNode):
            return self.catalog.comparison(node.data.operator).inputs
        if isinstance(node, GraphBrokerActionNode):
            return self.catalog.broker_action(node.data.action).inputs
        return ()

    def _node_display_name(self, node: GraphNode) -> str:
        if isinstance(node, GraphOperationNode):
            return OPERATION_DESCRIPTORS[node.data.operation].display_name
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


class _ResolvedOutput:
    def __init__(self, scalar_type: GraphScalarType, nullable: bool) -> None:
        self.scalar_type = scalar_type
        self.nullable = nullable
