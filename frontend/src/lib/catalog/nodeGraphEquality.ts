import type { GraphEdge, GraphNode, NodeGraph } from '$lib/api/generated';
import { GRAPH_NODE_TYPE } from './graphContracts';

export function nodeGraphsEqual(
  left: NodeGraph | undefined,
  right: NodeGraph | undefined
): boolean {
  if (!left || !right) return left === right;
  if (left.nodes.length !== right.nodes.length) return false;

  const leftEdges = left.edges ?? [];
  const rightEdges = right.edges ?? [];
  if (leftEdges.length !== rightEdges.length) return false;

  const leftNodeIds = new Set(left.nodes.map((node) => node.id));
  const leftEdgeIds = new Set(leftEdges.map((edge) => edge.id));
  const rightNodesById = new Map(right.nodes.map((node) => [node.id, node]));
  const rightEdgesById = new Map(rightEdges.map((edge) => [edge.id, edge]));
  return (
    leftNodeIds.size === left.nodes.length &&
    leftEdgeIds.size === leftEdges.length &&
    rightNodesById.size === right.nodes.length &&
    rightEdgesById.size === rightEdges.length &&
    left.nodes.every((node) => {
      const matchingNode = rightNodesById.get(node.id);
      return matchingNode !== undefined && graphNodesEqual(node, matchingNode);
    }) &&
    leftEdges.every((edge) => {
      const matchingEdge = rightEdgesById.get(edge.id);
      return matchingEdge !== undefined && graphEdgesEqual(edge, matchingEdge);
    })
  );
}

function graphNodesEqual(left: GraphNode, right: GraphNode): boolean {
  if (
    left.type !== right.type ||
    left.position.x !== right.position.x ||
    left.position.y !== right.position.y
  ) return false;

  switch (left.type) {
    case GRAPH_NODE_TYPE.trigger:
      return right.type === GRAPH_NODE_TYPE.trigger
        && left.data.hook_name === right.data.hook_name;
    case GRAPH_NODE_TYPE.constant:
      return right.type === GRAPH_NODE_TYPE.constant
        && left.data.scalar_type === right.data.scalar_type
        && left.data.value === right.data.value;
    case GRAPH_NODE_TYPE.comparison:
      return right.type === GRAPH_NODE_TYPE.comparison
        && left.data.operator === right.data.operator;
    case GRAPH_NODE_TYPE.brokerAction:
      return right.type === GRAPH_NODE_TYPE.brokerAction
        && left.data.action === right.data.action;
  }
}

function graphEdgesEqual(left: GraphEdge, right: GraphEdge): boolean {
  return left.source === right.source
    && left.source_handle === right.source_handle
    && left.target === right.target
    && left.target_handle === right.target_handle;
}
