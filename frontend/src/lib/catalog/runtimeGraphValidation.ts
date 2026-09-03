import type { GraphNode, GraphNodeCatalog, NodeGraph } from '$lib/api/generated';
import catalogContract from './catalogContract.fixture.json';
import {
  brokerActionForNode,
  canvasEdges,
  canvasNodes,
  comparisonForNode,
  connectionIsValid,
  constantForNode,
  triggerForNode,
  type CanvasNode
} from './nodeGraph';
import { GRAPH_NODE_TYPE } from './graphContracts';

const catalog = catalogContract.graphNodeCatalog as GraphNodeCatalog;

export function nodeGraphContractIsValid(graph: NodeGraph): boolean {
  try {
    return validateNodeGraphContract(graph);
  } catch {
    return false;
  }
}

function validateNodeGraphContract(graph: NodeGraph): boolean {
  const limits = catalogContract.nodeGraph;
  if (graph.nodes.length > limits.maximumNodes
    || (graph.edges ?? []).length > limits.maximumEdges
    || !hasUnique(graph.nodes.map(({ id }) => id))
    || !hasUnique((graph.edges ?? []).map(({ id }) => id))) return false;

  const nodes = canvasNodes(graph);
  if (!nodes.every(nodeMatchesCatalog)) return false;
  const triggerHooks = nodes
    .filter((node) => node.type === GRAPH_NODE_TYPE.trigger)
    .map((node) => node.data.hook_name);
  if (!hasUnique(triggerHooks)) return false;

  const edges = canvasEdges(graph);
  const acceptedEdges = [];
  for (const edge of edges) {
    if (!connectionIsValid(edge, nodes, acceptedEdges, catalog)) return false;
    acceptedEdges.push(edge);
  }

  const incoming = new Map(nodes.map(({ id }) => [id, [] as string[]]));
  const outgoing = new Map(nodes.map(({ id }) => [id, [] as string[]]));
  for (const edge of edges) {
    incoming.get(edge.target)?.push(edge.source);
    outgoing.get(edge.source)?.push(edge.target);
  }
  if (!requiredInputsConnected(nodes, edges)) return false;
  const topologicalOrder = topologicalNodeOrder(nodes, incoming, outgoing);
  if (topologicalOrder === null) return false;
  return branchesBelongToOneTrigger(nodes, topologicalOrder, incoming, outgoing);
}

function nodeMatchesCatalog(node: CanvasNode): boolean {
  switch (node.type) {
    case GRAPH_NODE_TYPE.trigger:
      triggerForNode(catalog, node.data);
      return true;
    case GRAPH_NODE_TYPE.constant:
      constantForNode(catalog, node.data);
      return true;
    case GRAPH_NODE_TYPE.comparison:
      comparisonForNode(catalog, node.data);
      return true;
    case GRAPH_NODE_TYPE.brokerAction:
      brokerActionForNode(catalog, node.data);
      return true;
  }
}

function requiredInputsConnected(
  nodes: CanvasNode[],
  edges: ReturnType<typeof canvasEdges>
): boolean {
  for (const node of nodes) {
    const inputs = nodeInputs(node);
    for (const input of inputs) {
      const count = edges.filter(
        (edge) => edge.target === node.id && edge.targetHandle === input.handle_id
      ).length;
      if (count > catalogContract.nodeGraph.maximumInputConnectionsPerHandle
        || (input.required
          && count === catalogContract.nodeGraph.noInputConnections)) return false;
    }
  }
  return true;
}

function nodeInputs(node: CanvasNode) {
  if (node.type === GRAPH_NODE_TYPE.comparison) {
    return comparisonForNode(catalog, node.data).inputs;
  }
  if (node.type === GRAPH_NODE_TYPE.brokerAction) {
    return brokerActionForNode(catalog, node.data).inputs;
  }
  return [];
}

function topologicalNodeOrder(
  nodes: CanvasNode[],
  incoming: Map<string, string[]>,
  outgoing: Map<string, string[]>
): string[] | null {
  const remainingIncoming = new Map(
    [...incoming].map(([id, sources]) => [id, sources.length])
  );
  const ready = nodes.filter(({ id }) => remainingIncoming.get(id) === 0).map(({ id }) => id);
  const order: string[] = [];
  while (ready.length) {
    const id = ready.shift();
    if (id === undefined) break;
    order.push(id);
    for (const target of outgoing.get(id) ?? []) {
      const count = (remainingIncoming.get(target) ?? 0) - 1;
      remainingIncoming.set(target, count);
      if (count === 0) ready.push(target);
    }
  }
  return order.length === nodes.length ? order : null;
}

function branchesBelongToOneTrigger(
  nodes: CanvasNode[],
  topologicalOrder: string[],
  incoming: Map<string, string[]>,
  outgoing: Map<string, string[]>
): boolean {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const ancestors = transitiveRelations(topologicalOrder, incoming);
  const descendants = transitiveRelations([...topologicalOrder].reverse(), outgoing);
  const triggerIds = new Set(
    nodes.filter(({ type }) => type === GRAPH_NODE_TYPE.trigger).map(({ id }) => id)
  );
  const actionIds = new Set(
    nodes.filter(({ type }) => type === GRAPH_NODE_TYPE.brokerAction).map(({ id }) => id)
  );
  for (const node of nodes) {
    if (node.type === GRAPH_NODE_TYPE.trigger) continue;
    const descendantActions = [...(descendants.get(node.id) ?? [])]
      .filter((id) => actionIds.has(id));
    if (descendantActions.length === 0) return false;
    const branchTriggers = new Set<string>();
    for (const actionId of descendantActions) {
      for (const ancestorId of ancestors.get(actionId) ?? []) {
        if (triggerIds.has(ancestorId)) branchTriggers.add(ancestorId);
      }
    }
    if (branchTriggers.size !== catalogContract.nodeGraph.requiredTriggerBranchCount
      || !nodesById.has(node.id)) return false;
  }
  return true;
}

function transitiveRelations(
  order: string[],
  direct: Map<string, string[]>
): Map<string, Set<string>> {
  const relations = new Map<string, Set<string>>();
  for (const id of order) {
    const related = new Set<string>([id]);
    for (const directId of direct.get(id) ?? []) {
      related.add(directId);
      for (const transitiveId of relations.get(directId) ?? []) related.add(transitiveId);
    }
    relations.set(id, related);
  }
  return relations;
}

function hasUnique(values: string[]): boolean {
  return new Set(values).size === values.length;
}
