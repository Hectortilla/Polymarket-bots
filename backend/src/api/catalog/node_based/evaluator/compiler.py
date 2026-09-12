"""Compile validated node graphs into event branches."""

from dataclasses import dataclass
from decimal import Decimal

from api.catalog.graphs.catalog import GRAPH_NODE_CATALOG
from api.catalog.graphs.catalog.functional import GraphBrokerActionDescriptor
from api.catalog.graphs.contracts import NodeGraph
from api.catalog.graphs.contracts.edges import GraphEdge
from api.catalog.graphs.contracts.nodes import GraphNode
from api.catalog.graphs.contracts.nodes.actions import GraphBrokerActionNode
from api.catalog.graphs.contracts.nodes.comparisons import GraphComparisonNode
from api.catalog.graphs.contracts.nodes.constants import GraphConstantNode
from api.catalog.graphs.contracts.nodes.operations import GraphOperationNode
from api.catalog.graphs.contracts.nodes.parameters import GraphParameterNode
from api.catalog.graphs.contracts.nodes.triggers import GraphTriggerNode
from api.catalog.graphs.topology import GraphTopology
from api.catalog.graphs.types import GraphHookName
from api.catalog.graphs.values import GraphScalarType
from api.catalog.node_based.evaluator import capabilities
from api.catalog.node_based.evaluator.contracts import OutputKey


@dataclass(frozen=True, slots=True)
class CompiledGraph:
    incoming: dict[str, dict[str, OutputKey]]
    outgoing: dict[str, tuple[GraphEdge, ...]]
    branches: dict[GraphHookName, tuple[GraphNode, ...]]
    constant_values: dict[str, object]
    action_descriptors: dict[str, GraphBrokerActionDescriptor]

    @classmethod
    def from_graph(cls, graph: NodeGraph) -> "CompiledGraph":
        return _GraphCompiler(graph).compile()


class _GraphCompiler:
    def __init__(self, graph: NodeGraph) -> None:
        self._graph = graph
        self._nodes = {node.id: node for node in graph.nodes}
        self._topology = GraphTopology.from_edges(self._nodes, graph.edges)

    def compile(self) -> CompiledGraph:
        for node in self._graph.nodes:
            if type(node) not in (
                GraphTriggerNode,
                GraphConstantNode,
                GraphParameterNode,
                GraphComparisonNode,
                GraphOperationNode,
                GraphBrokerActionNode,
            ):
                raise capabilities.UnsupportedGraphOperation(
                    f"Unsupported node: {node.id}"
                )
            if (
                isinstance(node, GraphOperationNode)
                and node.data.operation not in capabilities.EXECUTABLE_OPERATIONS
            ):
                raise capabilities.UnsupportedGraphOperation(
                    f"Execution unavailable for {node.data.operation} at node {node.id}"
                )
        return CompiledGraph(
            incoming=self._index_inputs(),
            outgoing=self._topology.outgoing,
            branches={
                node.data.hook_name: self._compile_branch(node.id)
                for node in self._graph.nodes
                if isinstance(node, GraphTriggerNode)
            },
            constant_values=self._source_values(),
            action_descriptors={
                node.id: GRAPH_NODE_CATALOG.broker_action(node.data.action)
                for node in self._graph.nodes
                if isinstance(node, GraphBrokerActionNode)
            },
        )

    def _source_values(self) -> dict[str, object]:
        values = {
            node.id: node.runtime_value()
            for node in self._graph.nodes
            if isinstance(node, GraphConstantNode)
        }
        for node in self._graph.nodes:
            if isinstance(node, GraphParameterNode):
                parameter = next(
                    p for p in self._graph.parameters if p.id == node.data.parameter_id
                )
                values[node.id] = (
                    Decimal(parameter.data.value)
                    if parameter.data.scalar_type is GraphScalarType.NUMBER
                    else parameter.data.value
                )
        return values

    def _compile_branch(self, trigger_id: str) -> tuple[GraphNode, ...]:
        branch_node_ids = self._topology.branch_node_ids(trigger_id)
        return tuple(
            self._nodes[node_id]
            for node_id in self._topology.topological_order
            if node_id in branch_node_ids
        )

    def _index_inputs(self) -> dict[str, dict[str, OutputKey]]:
        return {
            node_id: {
                edge.target_handle: (edge.source, edge.source_handle) for edge in edges
            }
            for node_id, edges in self._topology.incoming.items()
            if edges
        }
