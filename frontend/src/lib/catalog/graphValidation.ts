import type { GraphNode, NodeGraph } from '$lib/api/generated';
import {
  readableValidationMessage,
  requestValidationIssues
} from '$lib/api/requestErrors';
import { GRAPH_COLLECTION_FIELD, GRAPH_NODE_TYPE } from './graphContracts';

export type GraphValidationIssue = {
  location: string;
  message: string;
};

export const GRAPH_VALIDATION_COPY = {
  STRUCTURE: 'Graph structure',
  INTRO: 'Review each issue below, update the graph, then save again.',
  TITLE: 'Fix the graph before saving'
} as const;

export function graphValidationIssues(
  error: unknown,
  graph: NodeGraph
): GraphValidationIssue[] {
  const uniqueIssues = new Map<string, GraphValidationIssue>();

  for (const issue of requestValidationIssues(error)) {
    const presented = {
      location: graphIssueLocation(issue.loc, graph),
      message: readableValidationMessage(issue.msg)
    };
    uniqueIssues.set(`${presented.location}:${presented.message}`, presented);
  }

  return [...uniqueIssues.values()];
}

function graphIssueLocation(
  location: Array<string | number>,
  graph: NodeGraph
): string {
  const nodeIndex = indexedSegment(location, GRAPH_COLLECTION_FIELD.nodes);
  if (nodeIndex !== undefined) {
    const node = graph.nodes[nodeIndex];
    const nodeLocation = node
      ? `Node ${nodeIndex + 1}: ${graphNodeLabel(node)}`
      : `Node ${nodeIndex + 1}`;
    const field = graphFieldLabel(location);
    return field ? `${nodeLocation}, ${field}` : nodeLocation;
  }

  const edgeIndex = indexedSegment(location, GRAPH_COLLECTION_FIELD.edges);
  if (edgeIndex !== undefined) {
    const field = graphFieldLabel(location);
    return field
      ? `Connection ${edgeIndex + 1}, ${field}`
      : `Connection ${edgeIndex + 1}`;
  }

  if (location.includes(GRAPH_COLLECTION_FIELD.nodes)) return 'Node list';
  if (location.includes(GRAPH_COLLECTION_FIELD.edges)) return 'Connection list';
  return GRAPH_VALIDATION_COPY.STRUCTURE;
}

function indexedSegment(
  location: Array<string | number>,
  collection: (typeof GRAPH_COLLECTION_FIELD)[keyof typeof GRAPH_COLLECTION_FIELD]
): number | undefined {
  const collectionIndex = location.lastIndexOf(collection);
  const index = location[collectionIndex + 1];
  return typeof index === 'number' ? index : undefined;
}

function graphNodeLabel(node: GraphNode): string {
  switch (node.type) {
    case GRAPH_NODE_TYPE.trigger:
      return `${humanize(node.data.hook_name)} trigger`;
    case GRAPH_NODE_TYPE.constant:
      return `${humanize(node.data.scalar_type)} constant`;
    case GRAPH_NODE_TYPE.comparison:
      return `${humanize(node.data.operator)} comparison`;
    case GRAPH_NODE_TYPE.brokerAction:
      return `${humanize(node.data.action)} action`;
  }
}

function graphFieldLabel(location: Array<string | number>): string | undefined {
  const field = [...location]
    .reverse()
    .find((segment): segment is string => FIELD_LABELS[segment] !== undefined);
  return field ? FIELD_LABELS[field] : undefined;
}

const FIELD_LABELS: Record<string, string> = {
  action: 'Action',
  hook_name: 'Trigger',
  id: 'Identifier',
  operator: 'Operator',
  scalar_type: 'Value type',
  source: 'Source node',
  source_handle: 'Source output',
  target: 'Target node',
  target_handle: 'Target input',
  value: 'Value',
  x: 'Horizontal position',
  y: 'Vertical position'
};

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}
