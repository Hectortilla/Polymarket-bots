import type { GraphFieldPath, GraphNodeCatalog } from '$lib/api/generated';

export const TRIGGER_NODE_EDITOR_CONTEXT = Symbol('trigger-node-editor');

export type TriggerNodeEditorContext = {
  catalog: GraphNodeCatalog;
  setOutputSelected: (
    nodeId: string,
    path: GraphFieldPath,
    selected: boolean
  ) => void;
};
