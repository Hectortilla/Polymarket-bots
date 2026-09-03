import type {
  GraphBrokerActionDescriptor,
  GraphBrokerActionNode,
  GraphBrokerActionNodeData,
  GraphComparisonDescriptor,
  GraphComparisonNode,
  GraphComparisonNodeData,
  GraphConstantDescriptor,
  GraphConstantNode,
  GraphConstantNodeData,
  GraphEdge,
  GraphNode,
  GraphNodeCatalog,
  GraphTriggerDescriptor,
  GraphTriggerNode,
  GraphTriggerNodeData,
  NodeGraph
} from '$lib/api/generated';
import { addEdge, type Connection, type Edge, type Node } from '@xyflow/svelte';
import { constantDataFromDescriptor } from './constantNode';
import { GRAPH_NODE_TYPE } from './graphContracts';

export { GRAPH_NODE_TYPE } from './graphContracts';
export { nodeGraphsEqual } from './nodeGraphEquality';

export type GraphNodeData = GraphNode['data'];
export type CanvasNode =
  | Node<GraphTriggerNodeData, GraphTriggerNode['type']>
  | Node<GraphConstantNodeData, GraphConstantNode['type']>
  | Node<GraphComparisonNodeData, GraphComparisonNode['type']>
  | Node<GraphBrokerActionNodeData, GraphBrokerActionNode['type']>;
export type CanvasEdge = Edge;

export function canvasNodes(graph: NodeGraph): CanvasNode[] {
  return graph.nodes.map(toCanvasNode);
}

function toCanvasNode(node: GraphNode): CanvasNode {
  const common = {
    id: node.id,
    position: { ...node.position }
  };
  switch (node.type) {
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

export function canvasEdges(graph: NodeGraph): CanvasEdge[] {
  return (graph.edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    sourceHandle: edge.source_handle,
    target: edge.target,
    targetHandle: edge.target_handle
  }));
}

// Project the canvas onto the backend contract so Flow-only state is never persisted.
export function toPersistedNodeGraph(
  nodes: CanvasNode[],
  edges: CanvasEdge[]
): NodeGraph {
  return {
    nodes: nodes.map(toPersistedNode),
    edges: edges.map(toPersistedEdge)
  };
}

function toPersistedEdge(edge: CanvasEdge): GraphEdge {
  if (!hasCompleteHandles(edge)) {
    throw new Error('Connected graph edges require source and target handles');
  }
  return {
    id: edge.id,
    source: edge.source,
    source_handle: edge.sourceHandle,
    target: edge.target,
    target_handle: edge.targetHandle
  };
}

function toPersistedNode(node: CanvasNode): GraphNode {
  const common = {
    id: node.id,
    position: { x: node.position.x, y: node.position.y }
  };
  switch (node.type) {
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

export function createTriggerNode(
  nodes: CanvasNode[],
  trigger: GraphTriggerDescriptor
): CanvasNode {
  return {
    ...nextNodeBase(nodes, `trigger-${trigger.hook_name.replaceAll('_', '-')}`),
    type: trigger.node_type ?? GRAPH_NODE_TYPE.trigger,
    data: { hook_name: trigger.hook_name }
  };
}

export function createConstantNode(
  nodes: CanvasNode[],
  descriptor: GraphConstantDescriptor
): CanvasNode {
  return {
    ...nextNodeBase(nodes, `constant-${descriptor.scalar_type}`),
    type: descriptor.node_type ?? GRAPH_NODE_TYPE.constant,
    data: constantDataFromDescriptor(descriptor)
  };
}

export function createComparisonNode(
  nodes: CanvasNode[],
  descriptor: GraphComparisonDescriptor
): CanvasNode {
  return {
    ...nextNodeBase(nodes, `comparison-${descriptor.operator}`),
    type: descriptor.node_type ?? GRAPH_NODE_TYPE.comparison,
    data: { operator: descriptor.operator }
  };
}

export function createBrokerActionNode(
  nodes: CanvasNode[],
  descriptor: GraphBrokerActionDescriptor
): CanvasNode {
  return {
    ...nextNodeBase(nodes, `action-${descriptor.action}`),
    type: descriptor.node_type ?? GRAPH_NODE_TYPE.brokerAction,
    data: { action: descriptor.action }
  };
}

function nextNodeBase(
  nodes: CanvasNode[],
  idPrefix: string
): Pick<CanvasNode, 'id' | 'position'> {
  const id = uniqueNodeId(nodes, idPrefix);
  const index = nodes.length;
  return {
    id,
    position: {
      x: 80 + ((index * 220) % 660),
      y: 80 + Math.floor(index / 3) * 180
    }
  };
}

function uniqueNodeId(nodes: CanvasNode[], prefix: string): string {
  const ids = new Set(nodes.map((node) => node.id));
  if (!ids.has(prefix)) return prefix;
  let suffix = 2;
  while (ids.has(`${prefix}-${suffix}`)) suffix += 1;
  return `${prefix}-${suffix}`;
}

export function triggerAlreadyExists(
  nodes: CanvasNode[],
  trigger: GraphTriggerDescriptor
): boolean {
  return nodes.some(
    (node) =>
      node.type === GRAPH_NODE_TYPE.trigger &&
      node.data.hook_name === trigger.hook_name
  );
}

export function triggerForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphTriggerNodeData
): GraphTriggerDescriptor {
  const trigger = catalog.triggers.find(
    (candidate) => candidate.hook_name === nodeData.hook_name
  );
  if (!trigger) throw new Error(`Unknown graph trigger: ${nodeData.hook_name}`);
  return trigger;
}

export function constantForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphConstantNodeData
): GraphConstantDescriptor {
  const descriptor = catalog.constants.find(
    (candidate) => candidate.scalar_type === nodeData.scalar_type
  );
  if (!descriptor) throw new Error(`Unknown graph constant: ${nodeData.scalar_type}`);
  return descriptor;
}

export function comparisonForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphComparisonNodeData
): GraphComparisonDescriptor {
  const descriptor = catalog.comparisons.find(
    (candidate) => candidate.operator === nodeData.operator
  );
  if (!descriptor) throw new Error(`Unknown graph comparison: ${nodeData.operator}`);
  return descriptor;
}

export function brokerActionForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphBrokerActionNodeData
): GraphBrokerActionDescriptor {
  const descriptor = catalog.broker_actions.find(
    (candidate) => candidate.action === nodeData.action
  );
  if (!descriptor) throw new Error(`Unknown graph broker action: ${nodeData.action}`);
  return descriptor;
}

export function connectionIsValid(
  connection: Connection | CanvasEdge,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  catalog: GraphNodeCatalog
): boolean {
  if (!hasCompleteHandles(connection)) return false;
  if (
    edges.some(
      (edge) =>
        edge.target === connection.target && edge.targetHandle === connection.targetHandle
    )
  ) {
    return false;
  }
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target || source.id === target.id) return false;
  const sourceScalarType = graphOutputScalarType(
    source,
    connection.sourceHandle,
    catalog
  );
  const acceptedScalarTypes = inputScalarTypes(
    target,
    connection.targetHandle,
    catalog
  );
  if (target.type === GRAPH_NODE_TYPE.comparison) {
    const connectedScalarTypes = edges
      .filter((edge) => edge.target === target.id)
      .map((edge) => {
        const connectedSource = nodes.find((node) => node.id === edge.source);
        return connectedSource && edge.sourceHandle
          ? graphOutputScalarType(connectedSource, edge.sourceHandle, catalog)
          : null;
      });
    if (connectedScalarTypes.some((type) => type !== sourceScalarType)) return false;
  }
  return (
    sourceScalarType !== null && acceptedScalarTypes.includes(sourceScalarType)
  );
}

export function addConnection(
  connection: Connection,
  edges: CanvasEdge[]
): CanvasEdge[] {
  return addEdge(connection, edges);
}

export function graphOutputScalarType(
  node: CanvasNode,
  handleId: string,
  catalog: GraphNodeCatalog
) {
  if (node.type === GRAPH_NODE_TYPE.trigger) {
    const trigger = triggerForNode(catalog, node.data);
    return (
      trigger.payload?.fields.find((field) => field.handle_id === handleId)
        ?.scalar_type ?? null
    );
  }
  if (node.type === GRAPH_NODE_TYPE.constant) {
    return constantForNode(catalog, node.data).output.scalar_type;
  }
  if (node.type === GRAPH_NODE_TYPE.comparison) {
    return comparisonForNode(catalog, node.data).output.scalar_type;
  }
  return null;
}

function inputScalarTypes(
  node: CanvasNode,
  handleId: string,
  catalog: GraphNodeCatalog
) {
  const inputs = inputsForNode(node, catalog);
  return inputs.find((input) => input.handle_id === handleId)?.scalar_types ?? [];
}

function inputsForNode(node: CanvasNode, catalog: GraphNodeCatalog) {
  if (node.type === GRAPH_NODE_TYPE.comparison) {
    return comparisonForNode(catalog, node.data).inputs;
  }
  if (node.type === GRAPH_NODE_TYPE.brokerAction) {
    return brokerActionForNode(catalog, node.data).inputs;
  }
  return [];
}

function hasCompleteHandles(
  connection: Connection | CanvasEdge
): connection is (Connection | CanvasEdge) & {
  sourceHandle: string;
  targetHandle: string;
} {
  return Boolean(connection.sourceHandle && connection.targetHandle);
}
