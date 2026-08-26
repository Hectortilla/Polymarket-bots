import type {
  GraphComparisonNodeData,
  GraphConstantNodeData,
  GraphNodeCatalog
} from '$lib/api/generated';

export const NODE_GRAPH_EDITOR_CONTEXT = Symbol('node-graph-editor');

export type NodeGraphEditorContext = {
  catalog: GraphNodeCatalog;
  setComparisonData: (nodeId: string, data: GraphComparisonNodeData) => void;
  setConstantData: (nodeId: string, data: GraphConstantNodeData) => void;
};
