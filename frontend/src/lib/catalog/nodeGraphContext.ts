import type { NodeGraphCatalog } from "$lib/catalog/nodeGraph/catalog";
import type {
  GraphComparisonNodeData,
  GraphConstantNodeData,
  GraphOperationNodeData,
  GraphParameter,
  GraphNodeCatalog,
} from "$lib/api/generated";

export const NODE_GRAPH_EDITOR_CONTEXT = Symbol("node-graph-editor");

export type NodeGraphEditorContext = {
  catalog: GraphNodeCatalog;
  resolver: NodeGraphCatalog;
  parameters: GraphParameter[];
  setOperationData: (nodeId: string, data: GraphOperationNodeData) => void;
  readOnly: boolean;
  issuesForNode?: (nodeId: string) => string[];
  setComparisonData: (nodeId: string, data: GraphComparisonNodeData) => void;
  setConstantData: (nodeId: string, data: GraphConstantNodeData) => void;
};
