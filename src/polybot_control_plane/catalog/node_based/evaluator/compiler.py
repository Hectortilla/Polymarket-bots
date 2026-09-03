"""Compile validated node graphs into event branches."""

from dataclasses import dataclass

from polybot_control_plane.catalog.graphs.catalog import (
    GRAPH_NODE_CATALOG,
    GraphBrokerActionDescriptor,
)
from polybot_control_plane.catalog.graphs.contracts import (
    GraphBrokerActionNode,
    GraphConstantNode,
    GraphEdge,
    GraphNode,
    GraphTriggerNode,
    NodeGraph,
)
from polybot_control_plane.catalog.graphs.topology import GraphTopology
from polybot_control_plane.catalog.graphs.types import GraphHookName
from polybot_control_plane.catalog.node_based.evaluator.contracts import OutputKey


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
        return CompiledGraph(
            incoming=self._index_inputs(),
            outgoing=self._topology.outgoing,
            branches={
                node.data.hook_name: self._compile_branch(node.id)
                for node in self._graph.nodes
                if isinstance(node, GraphTriggerNode)
            },
            constant_values={
                node.id: node.runtime_value()
                for node in self._graph.nodes
                if isinstance(node, GraphConstantNode)
            },
            action_descriptors={
                node.id: GRAPH_NODE_CATALOG.broker_action(node.data.action)
                for node in self._graph.nodes
                if isinstance(node, GraphBrokerActionNode)
            },
        )

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
                edge.target_handle: (edge.source, edge.source_handle)
                for edge in edges
            }
            for node_id, edges in self._topology.incoming.items()
            if edges
        }
