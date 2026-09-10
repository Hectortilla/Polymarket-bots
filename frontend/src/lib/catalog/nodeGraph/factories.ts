import { DEFAULT_OPERATION_SCALAR_TYPE } from "$lib/catalog/graphContracts";

import type {
  GraphBrokerActionDescriptor,
  GraphComparisonDescriptor,
  GraphConstantDescriptor,
  GraphOperationDescriptor,
  GraphParameter,
  GraphTriggerDescriptor,
} from "$lib/api/generated";

import { constantDataFromDescriptor } from "$lib/catalog/constantNode";

import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";

import { type CanvasNode } from "$lib/catalog/nodeGraph/contracts";

export function createTriggerNode(nodes: CanvasNode[], trigger: GraphTriggerDescriptor): CanvasNode {
  return {
    ...nextNodeBase(nodes, `trigger-${trigger.hook_name.replaceAll("_", "-")}`),
    type: trigger.node_type ?? GRAPH_NODE_TYPE.trigger,
    data: { hook_name: trigger.hook_name },
  };
}

export function createConstantNode(nodes: CanvasNode[], descriptor: GraphConstantDescriptor): CanvasNode {
  return {
    ...nextNodeBase(nodes, `constant-${descriptor.scalar_type}`),
    type: descriptor.node_type ?? GRAPH_NODE_TYPE.constant,
    data: constantDataFromDescriptor(descriptor),
  };
}

export function createComparisonNode(nodes: CanvasNode[], descriptor: GraphComparisonDescriptor): CanvasNode {
  return {
    ...nextNodeBase(nodes, `comparison-${descriptor.operator}`),
    type: descriptor.node_type ?? GRAPH_NODE_TYPE.comparison,
    data: { operator: descriptor.operator },
  };
}

export function createBrokerActionNode(nodes: CanvasNode[], descriptor: GraphBrokerActionDescriptor): CanvasNode {
  return {
    ...nextNodeBase(nodes, `action-${descriptor.action}`),
    type: descriptor.node_type ?? GRAPH_NODE_TYPE.brokerAction,
    data: { action: descriptor.action },
  };
}

export function createOperationNode(nodes: CanvasNode[], descriptor: GraphOperationDescriptor): CanvasNode {
  return {
    ...nextNodeBase(nodes, descriptor.operation),
    type: GRAPH_NODE_TYPE.operation,
    data: {
      operation: descriptor.operation,
      scalar_type: DEFAULT_OPERATION_SCALAR_TYPE,
      input_ids: descriptor.expandable ? descriptor.inputs.map((port) => port.handle_id) : [],
    },
  };
}

export function createParameterNode(nodes: CanvasNode[], parameter: GraphParameter): CanvasNode {
  return {
    ...nextNodeBase(nodes, GRAPH_NODE_TYPE.parameter),
    type: GRAPH_NODE_TYPE.parameter,
    data: { parameter_id: parameter.id },
  };
}

function nextNodeBase(nodes: CanvasNode[], idPrefix: string): Pick<CanvasNode, "id" | "position"> {
  const id = uniqueNodeId(nodes, idPrefix);
  const index = nodes.length;
  return {
    id,
    position: {
      x: 80 + ((index * 220) % 660),
      y: 80 + Math.floor(index / 3) * 180,
    },
  };
}

function uniqueNodeId(nodes: CanvasNode[], prefix: string): string {
  const ids = new Set(nodes.map((node) => node.id));
  if (!ids.has(prefix)) return prefix;
  let suffix = 2;
  while (ids.has(`${prefix}-${suffix}`)) suffix += 1;
  return `${prefix}-${suffix}`;
}
