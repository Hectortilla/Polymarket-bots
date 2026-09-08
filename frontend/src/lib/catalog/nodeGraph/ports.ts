import { GRAPH_FIELD_COPY } from '$lib/catalog/copy';

import { DEFAULT_OPERATION_SCALAR_TYPE } from '$lib/catalog/graphContracts';

import type {
  GraphInputDescriptor,
  GraphNodeCatalog,
  GraphOutputDescriptor,
  GraphParameter,
} from '$lib/api/generated';

import catalogContract from '$lib/catalog/catalogContract.fixture.json';

import { GRAPH_CONTEXT_PORT_TYPE, GRAPH_NODE_TYPE } from '$lib/catalog/graphContracts';

import { type CanvasNode } from '$lib/catalog/nodeGraph/contracts';

import {
  brokerActionForNode,
  comparisonForNode,
  constantForNode,
  operationForNode,
  triggerForNode,
} from '$lib/catalog/nodeGraph/catalog';

export function outputsForNode(
  node: CanvasNode,
  catalog: GraphNodeCatalog,
  parameters: GraphParameter[] = [],
): GraphOutputDescriptor[] {
  if (node.type === GRAPH_NODE_TYPE.trigger) {
    const trigger = triggerForNode(catalog, node.data);
    return triggerOutputs(trigger);
  }
  if (node.type === GRAPH_NODE_TYPE.constant) return [constantForNode(catalog, node.data).output];
  if (node.type === GRAPH_NODE_TYPE.comparison)
    return [comparisonForNode(catalog, node.data).output];
  if (node.type === GRAPH_NODE_TYPE.brokerAction)
    return brokerActionForNode(catalog, node.data).outputs ?? [];
  if (node.type === GRAPH_NODE_TYPE.parameter) {
    const parameter = parameters.find((p) => p.id === node.data.parameter_id);
    return parameter
      ? [
          {
            handle_id: catalogContract.graphPort.VALUE,
            display_name: GRAPH_FIELD_COPY.VALUE,
            scalar_type: parameter.data.scalar_type,
          },
        ]
      : [];
  }
  const descriptor = operationForNode(catalog, node.data);
  return descriptor.outputs.map((port) =>
    descriptor.selectable_scalar_type
      ? { ...port, scalar_type: node.data.scalar_type ?? DEFAULT_OPERATION_SCALAR_TYPE }
      : port,
  );
}

export function graphOutputScalarType(
  node: CanvasNode,
  handleId: string,
  catalog: GraphNodeCatalog,
  parameters: GraphParameter[] = [],
) {
  return (
    outputsForNode(node, catalog, parameters).find((port) => port.handle_id === handleId)
      ?.scalar_type ?? null
  );
}

export function inputsForNode(node: CanvasNode, catalog: GraphNodeCatalog): GraphInputDescriptor[] {
  if (node.type === GRAPH_NODE_TYPE.comparison) return comparisonForNode(catalog, node.data).inputs;
  if (node.type === GRAPH_NODE_TYPE.brokerAction)
    return brokerActionForNode(catalog, node.data).inputs;
  if (node.type !== GRAPH_NODE_TYPE.operation) return [];
  const descriptor = operationForNode(catalog, node.data);
  if (descriptor.expandable) return expandableInputs(node, descriptor);
  return typedInputs(node, descriptor);
}

function triggerOutputs(trigger: ReturnType<typeof triggerForNode>): GraphOutputDescriptor[] {
  const outputs: GraphOutputDescriptor[] = [
    {
      handle_id: trigger.context_handle_id,
      display_name: 'Context',
      scalar_type: GRAPH_CONTEXT_PORT_TYPE,
    },
  ];
  for (const field of trigger.payload?.fields ?? []) {
    if (field.scalar_type === null) continue;
    outputs.push({
      handle_id: field.handle_id,
      display_name: field.display_name,
      scalar_type: field.scalar_type,
      nullable: field.nullable,
    });
  }
  return outputs;
}

function expandableInputs(
  node: Extract<CanvasNode, { type: typeof GRAPH_NODE_TYPE.operation }>,
  descriptor: ReturnType<typeof operationForNode>,
): GraphInputDescriptor[] {
  const inputHandleIds = node.data.input_ids?.length
    ? node.data.input_ids
    : descriptor.inputs.map((port) => port.handle_id);
  return inputHandleIds.map((inputHandleId) => ({
    ...descriptor.inputs[0],
    handle_id: inputHandleId,
    display_name: inputHandleId,
  }));
}

function typedInputs(
  node: Extract<CanvasNode, { type: typeof GRAPH_NODE_TYPE.operation }>,
  descriptor: ReturnType<typeof operationForNode>,
): GraphInputDescriptor[] {
  return descriptor.inputs.map((port) => {
    if (
      !descriptor.selectable_scalar_type ||
      port.handle_id === catalogContract.graphPort.CONDITION
    )
      return port;
    return { ...port, scalar_types: [node.data.scalar_type ?? DEFAULT_OPERATION_SCALAR_TYPE] };
  });
}
