import type {
  GraphNodeData,
  GraphNodeType,
  NodeGraph
} from '$lib/api/generated';
import type { Edge, Node } from '@xyflow/svelte';

export const GRAPH_NODE_TYPE = {
  input: 'input',
  default: 'default',
  output: 'output'
} as const satisfies Record<string, GraphNodeType>;

const GRAPH_NODE_LABEL: Record<GraphNodeType, string> = {
  [GRAPH_NODE_TYPE.input]: 'Market input',
  [GRAPH_NODE_TYPE.default]: 'Condition',
  [GRAPH_NODE_TYPE.output]: 'Output'
};

export type CanvasNode = Node<GraphNodeData, GraphNodeType>;
export type CanvasEdge = Edge;

export function canvasNodes(graph: NodeGraph): CanvasNode[] {
  return graph.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    position: { ...node.position },
    data: { ...node.data }
  }));
}

export function canvasEdges(graph: NodeGraph): CanvasEdge[] {
  return (graph.edges ?? []).map((edge) => ({ ...edge }));
}

// Project the canvas onto the backend contract so XYFlow-only state is never persisted.
export function toPersistedNodeGraph(
  schemaVersion: NodeGraph['schema_version'],
  nodes: CanvasNode[],
  edges: CanvasEdge[]
): NodeGraph {
  return {
    schema_version: schemaVersion,
    nodes: nodes.map(({ id, type, position, data }) => ({
      id,
      type: type ?? GRAPH_NODE_TYPE.default,
      position: { x: position.x, y: position.y },
      data: { label: data.label }
    })),
    edges: edges.map(({ id, source, target }) => ({ id, source, target }))
  };
}

export function createCanvasNode(
  nodes: CanvasNode[],
  type: GraphNodeType
): CanvasNode {
  const sequence = firstAvailableSequence(nodes, type);
  return {
    id: `${type}-${sequence}`,
    type,
    position: {
      x: 80 + ((nodes.length * 160) % 640),
      y: 80 + Math.floor(nodes.length / 4) * 120
    },
    data: { label: GRAPH_NODE_LABEL[type] }
  };
}

function firstAvailableSequence(nodes: CanvasNode[], type: GraphNodeType): number {
  const ids = new Set(nodes.map((node) => node.id));
  let sequence = 1;
  while (ids.has(`${type}-${sequence}`)) sequence += 1;
  return sequence;
}
