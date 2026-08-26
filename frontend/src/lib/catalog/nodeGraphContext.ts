import type {
  GraphConstantNodeData,
  GraphNodeCatalog
} from '$lib/api/generated';

export const NODE_GRAPH_EDITOR_CONTEXT = Symbol('node-graph-editor');

export type NodeGraphEditorContext = {
  catalog: GraphNodeCatalog;
  setConstantData: (nodeId: string, data: GraphConstantNodeData) => void;
};
