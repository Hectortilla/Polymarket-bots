import type {
  BotDefinitionDescriptor,
  GraphNode,
  GraphNodeCatalog,
  GraphScalarType,
  NodeGraph
} from '$lib/api/generated';
import catalogContract from './catalogContract.fixture.json';

type GraphNodeTypeContract = {
  [Key in keyof typeof catalogContract.graphNodeType]: Extract<
    GraphNode['type'],
    Lowercase<Key>
  >;
};
type GraphScalarTypeContract = {
  [Key in keyof typeof catalogContract.graphScalarType]: Extract<
    GraphScalarType,
    Lowercase<Key>
  >;
};

const graphNodeTypeContract = catalogContract.graphNodeType as GraphNodeTypeContract;
const graphScalarTypeContract = catalogContract.graphScalarType as GraphScalarTypeContract;

export const GRAPH_SCALAR_TYPE = {
  boolean: graphScalarTypeContract.BOOLEAN,
  integer: graphScalarTypeContract.INTEGER,
  decimal: graphScalarTypeContract.DECIMAL,
  string: graphScalarTypeContract.STRING
} as const satisfies Record<string, GraphScalarType>;

export const GRAPH_NODE_TYPE = {
  trigger: graphNodeTypeContract.TRIGGER,
  constant: graphNodeTypeContract.CONSTANT,
  comparison: graphNodeTypeContract.COMPARISON,
  brokerAction: graphNodeTypeContract.BROKER_ACTION
} as const satisfies Record<string, GraphNode['type']>;

export const GRAPH_COLLECTION_FIELD = {
  nodes: 'nodes',
  edges: 'edges'
} as const satisfies Record<string, keyof NodeGraph>;

export type GraphCapableDefinition = BotDefinitionDescriptor & {
  graph_catalog: GraphNodeCatalog;
  starter_graph: NodeGraph;
};

export function hasGraphCapability(
  descriptor: BotDefinitionDescriptor | undefined
): descriptor is GraphCapableDefinition {
  return Boolean(descriptor?.graph_catalog && descriptor.starter_graph);
}

export function cloneNodeGraph(graph: NodeGraph): NodeGraph {
  return JSON.parse(JSON.stringify(graph)) as NodeGraph;
}
