import type {
  GraphBrokerActionDescriptor,
  GraphBrokerActionNodeData,
  GraphComparisonDescriptor,
  GraphComparisonNodeData,
  GraphConstantDescriptor,
  GraphConstantNodeData,
  GraphNodeCatalog,
  GraphOperationDescriptor,
  GraphOperationNode,
  GraphTriggerDescriptor,
  GraphTriggerNodeData,
} from '$lib/api/generated';

import { GRAPH_NODE_TYPE } from '$lib/catalog/graphContracts';

import { type CanvasNode } from '$lib/catalog/nodeGraph/contracts';

export function triggerAlreadyExists(
  nodes: CanvasNode[],
  trigger: GraphTriggerDescriptor,
): boolean {
  return nodes.some(
    (node) => node.type === GRAPH_NODE_TYPE.trigger && node.data.hook_name === trigger.hook_name,
  );
}

export function triggerForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphTriggerNodeData,
): GraphTriggerDescriptor {
  const trigger = catalog.triggers.find((candidate) => candidate.hook_name === nodeData.hook_name);
  if (!trigger) throw new Error(`Unknown graph trigger: ${nodeData.hook_name}`);
  return trigger;
}

export function constantForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphConstantNodeData,
): GraphConstantDescriptor {
  const descriptor = catalog.constants.find(
    (candidate) => candidate.scalar_type === nodeData.scalar_type,
  );
  if (!descriptor) throw new Error(`Unknown graph constant: ${nodeData.scalar_type}`);
  return descriptor;
}

export function comparisonForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphComparisonNodeData,
): GraphComparisonDescriptor {
  const descriptor = catalog.comparisons.find(
    (candidate) => candidate.operator === nodeData.operator,
  );
  if (!descriptor) throw new Error(`Unknown graph comparison: ${nodeData.operator}`);
  return descriptor;
}

export function brokerActionForNode(
  catalog: GraphNodeCatalog,
  nodeData: GraphBrokerActionNodeData,
): GraphBrokerActionDescriptor {
  const descriptor = catalog.broker_actions.find(
    (candidate) => candidate.action === nodeData.action,
  );
  if (!descriptor) throw new Error(`Unknown graph broker action: ${nodeData.action}`);
  return descriptor;
}

export function operationForNode(
  catalog: GraphNodeCatalog,
  data: GraphOperationNode['data'],
): GraphOperationDescriptor {
  const descriptor = catalog.operations?.find((item) => item.operation === data.operation);
  if (!descriptor) throw new Error(`Unknown operation: ${data.operation}`);
  return descriptor;
}
