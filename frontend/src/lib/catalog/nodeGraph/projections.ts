import type { GraphEdge, GraphNode, GraphParameter, NodeGraph } from "$lib/api/generated";

import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";

import { type CanvasEdge, type CanvasNode, hasCompleteHandles } from "$lib/catalog/nodeGraph/contracts";

export function canvasNodes(graph: NodeGraph): CanvasNode[] {
  return graph.nodes.map(toCanvasNode);
}

export function canvasEdges(graph: NodeGraph): CanvasEdge[] {
  return (graph.edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    sourceHandle: edge.source_handle,
    target: edge.target,
    targetHandle: edge.target_handle,
  }));
}

export function toPersistedNodeGraph(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  parameters: GraphParameter[] = [],
): NodeGraph {
  return {
    ...(parameters.length ? { parameters } : {}),
    nodes: nodes.map(toPersistedNode),
    edges: edges.map(toPersistedEdge),
  };
}

function toCanvasNode(node: GraphNode): CanvasNode {
  const common = {
    id: node.id,
    position: { ...node.position },
  };
  switch (node.type) {
    case GRAPH_NODE_TYPE.operation:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.parameter:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.trigger:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.constant:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.comparison:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.brokerAction:
      return { ...common, type: node.type, data: { ...node.data } };
  }
}

function toPersistedEdge(edge: CanvasEdge): GraphEdge {
  if (!hasCompleteHandles(edge)) {
    throw new Error("Connected graph edges require source and target handles");
  }
  return {
    id: edge.id,
    source: edge.source,
    source_handle: edge.sourceHandle,
    target: edge.target,
    target_handle: edge.targetHandle,
  };
}

function toPersistedNode(node: CanvasNode): GraphNode {
  const common = {
    id: node.id,
    position: { x: node.position.x, y: node.position.y },
  };
  switch (node.type) {
    case GRAPH_NODE_TYPE.operation:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.parameter:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.trigger:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.constant:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.comparison:
      return { ...common, type: node.type, data: { ...node.data } };
    case GRAPH_NODE_TYPE.brokerAction:
      return { ...common, type: node.type, data: { ...node.data } };
  }
}
