import type {
  GraphEdge,
  GraphFieldPath,
  GraphNode,
  GraphNodeCatalog,
  GraphNodeData,
  GraphTriggerDescriptor,
  NodeGraph
} from '$lib/api/generated';
import type { Edge, Node } from '@xyflow/svelte';

export type CanvasNode = Node<GraphNodeData, GraphNode['type']>;
export type CanvasEdge = Edge;

export function canvasNodes(graph: NodeGraph): CanvasNode[] {
  return graph.nodes.map((node) => ({
    id: node.id,
    type: node.type,
    position: { ...node.position },
    data: cloneNodeData(node.data)
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
      type,
      position: { x: position.x, y: position.y },
      data: cloneNodeData(data)
    })),
    edges: edges.map(({ id, source, target }): GraphEdge => ({
      id,
      source,
      target
    }))
  };
}

export function createTriggerNode(
  nodes: CanvasNode[],
  catalog: GraphNodeCatalog,
  trigger: GraphTriggerDescriptor
): CanvasNode {
  return {
    id: `trigger-${trigger.hook_name.replaceAll('_', '-')}`,
    type: catalog.node_type,
    position: {
      x: 80 + ((nodes.length * 220) % 660),
      y: 80 + Math.floor(nodes.length / 3) * 180
    },
    data: {
      hook_name: trigger.hook_name,
      selected_output_paths: []
    }
  };
}

export function triggerAlreadyExists(
  nodes: CanvasNode[],
  trigger: GraphTriggerDescriptor
): boolean {
  return nodes.some((node) => node.data.hook_name === trigger.hook_name);
}

export function triggerForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphNodeData
): GraphTriggerDescriptor {
  const trigger = catalog.triggers.find(
    (candidate) => candidate.hook_name === nodeData.hook_name
  );
  if (!trigger) {
    throw new Error(`Unknown graph trigger: ${nodeData.hook_name}`);
  }
  return trigger;
}

export function setOutputPathSelected(
  nodeData: GraphNodeData,
  path: GraphFieldPath,
  selected: boolean
): GraphNodeData {
  const selectedPaths = nodeData.selected_output_paths ?? [];
  const pathKey = graphFieldPathKey(path);
  const withoutPath = selectedPaths.filter(
    (candidate) => graphFieldPathKey(candidate) !== pathKey
  );
  return {
    ...nodeData,
    selected_output_paths: selected ? [...withoutPath, clonePath(path)] : withoutPath
  };
}

export function outputPathIsSelected(
  nodeData: GraphNodeData,
  path: GraphFieldPath
): boolean {
  const pathKey = graphFieldPathKey(path);
  return (nodeData.selected_output_paths ?? []).some(
    (candidate) => graphFieldPathKey(candidate) === pathKey
  );
}

function graphFieldPathKey(path: GraphFieldPath): string {
  return path.segments.join('.');
}

function cloneNodeData(data: GraphNodeData): GraphNodeData {
  return {
    ...data,
    hook_name: data.hook_name,
    selected_output_paths: (data.selected_output_paths ?? []).map(clonePath)
  };
}

function clonePath(path: GraphFieldPath): GraphFieldPath {
  return { segments: [...path.segments] };
}
