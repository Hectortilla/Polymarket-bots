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
  GraphInputDescriptor,
  GraphOutputDescriptor,
  GraphParameter,
} from "$lib/api/generated";
import type { Connection } from "@xyflow/svelte";
import { GRAPH_FIELD_COPY } from "$lib/catalog/copy";
import { DEFAULT_OPERATION_SCALAR_TYPE, GRAPH_NODE_TYPE, GRAPH_CONTEXT_PORT_TYPE } from "$lib/catalog/graphContracts";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import { type CanvasNode, type CanvasEdge, hasCompleteHandles } from "./contracts";

export class NodeGraphCatalog {
  constructor(readonly catalog: GraphNodeCatalog) {}

  triggerForNode(nodeData: GraphTriggerNodeData): GraphTriggerDescriptor {
    const trigger = this.catalog.triggers.find((candidate) => candidate.hook_name === nodeData.hook_name);
    if (!trigger) throw new Error(`Unknown graph trigger: ${nodeData.hook_name}`);
    return trigger;
  }

  constantForNode(nodeData: GraphConstantNodeData): GraphConstantDescriptor {
    const descriptor = this.catalog.constants.find((candidate) => candidate.scalar_type === nodeData.scalar_type);
    if (!descriptor) throw new Error(`Unknown graph constant: ${nodeData.scalar_type}`);
    return descriptor;
  }

  comparisonForNode(nodeData: GraphComparisonNodeData): GraphComparisonDescriptor {
    const descriptor = this.catalog.comparisons.find((candidate) => candidate.operator === nodeData.operator);
    if (!descriptor) throw new Error(`Unknown graph comparison: ${nodeData.operator}`);
    return descriptor;
  }

  brokerActionForNode(nodeData: GraphBrokerActionNodeData): GraphBrokerActionDescriptor {
    const descriptor = this.catalog.broker_actions.find((candidate) => candidate.action === nodeData.action);
    if (!descriptor) throw new Error(`Unknown graph broker action: ${nodeData.action}`);
    return descriptor;
  }

  operationForNode(nodeData: GraphOperationNode["data"]): GraphOperationDescriptor {
    const descriptor = this.catalog.operations?.find((item) => item.operation === nodeData.operation);
    if (!descriptor) throw new Error(`Unknown operation: ${nodeData.operation}`);
    return descriptor;
  }

  outputsForNode(node: CanvasNode, parameters: GraphParameter[] = []): GraphOutputDescriptor[] {
    if (node.type === GRAPH_NODE_TYPE.trigger) {
      const trigger = this.triggerForNode(node.data);
      return this.triggerOutputs(trigger);
    }
    if (node.type === GRAPH_NODE_TYPE.constant) return [this.constantForNode(node.data).output];
    if (node.type === GRAPH_NODE_TYPE.comparison) return [this.comparisonForNode(node.data).output];
    if (node.type === GRAPH_NODE_TYPE.brokerAction) return this.brokerActionForNode(node.data).outputs ?? [];
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
    const descriptor = this.operationForNode(node.data);
    return descriptor.outputs.map((port) =>
      descriptor.selectable_scalar_type
        ? { ...port, scalar_type: node.data.scalar_type ?? DEFAULT_OPERATION_SCALAR_TYPE }
        : port,
    );
  }

  graphOutputScalarType(node: CanvasNode, handleId: string, parameters: GraphParameter[] = []) {
    return this.outputsForNode(node, parameters).find((port) => port.handle_id === handleId)?.scalar_type ?? null;
  }

  inputsForNode(node: CanvasNode): GraphInputDescriptor[] {
    if (node.type === GRAPH_NODE_TYPE.comparison) return this.comparisonForNode(node.data).inputs;
    if (node.type === GRAPH_NODE_TYPE.brokerAction) return this.brokerActionForNode(node.data).inputs;
    if (node.type !== GRAPH_NODE_TYPE.operation) return [];
    const descriptor = this.operationForNode(node.data);
    if (descriptor.expandable) return this.expandableInputs(node, descriptor);
    return this.typedInputs(node, descriptor);
  }

  connectionIsValid(
    connection: Connection | CanvasEdge,
    nodes: CanvasNode[],
    edges: CanvasEdge[],
    parameters: GraphParameter[] = [],
  ): boolean {
    if (!hasCompleteHandles(connection)) return false;
    if (edges.some((edge) => edge.target === connection.target && edge.targetHandle === connection.targetHandle)) {
      return false;
    }
    const source = nodes.find((node) => node.id === connection.source);
    const target = nodes.find((node) => node.id === connection.target);
    if (!source || !target || source.id === target.id) return false;
    const sourceScalarType = this.graphOutputScalarType(source, connection.sourceHandle, parameters);
    const acceptedScalarTypes = this.inputScalarTypes(target, connection.targetHandle);
    if (
      target.type === GRAPH_NODE_TYPE.comparison &&
      !this.comparisonInputsMatchSourceType(target.id, sourceScalarType, nodes, edges, parameters)
    )
      return false;
    return sourceScalarType !== null && acceptedScalarTypes.includes(sourceScalarType);
  }

  private triggerOutputs(trigger: GraphTriggerDescriptor): GraphOutputDescriptor[] {
    const outputs: GraphOutputDescriptor[] = [
      {
        handle_id: trigger.context_handle_id,
        display_name: "Context",
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

  private expandableInputs(
    node: Extract<CanvasNode, { type: typeof GRAPH_NODE_TYPE.operation }>,
    descriptor: GraphOperationDescriptor,
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

  private typedInputs(
    node: Extract<CanvasNode, { type: typeof GRAPH_NODE_TYPE.operation }>,
    descriptor: GraphOperationDescriptor,
  ): GraphInputDescriptor[] {
    return descriptor.inputs.map((port) => {
      if (!descriptor.selectable_scalar_type || port.handle_id === catalogContract.graphPort.CONDITION) return port;
      return { ...port, scalar_types: [node.data.scalar_type ?? DEFAULT_OPERATION_SCALAR_TYPE] };
    });
  }

  private inputScalarTypes(node: CanvasNode, handleId: string) {
    return this.inputsForNode(node).find((input) => input.handle_id === handleId)?.scalar_types ?? [];
  }

  private comparisonInputsMatchSourceType(
    targetNodeId: string,
    sourceScalarType: ReturnType<NodeGraphCatalog["graphOutputScalarType"]>,
    nodes: CanvasNode[],
    edges: CanvasEdge[],
    parameters: GraphParameter[],
  ): boolean {
    return edges
      .filter((edge) => edge.target === targetNodeId)
      .every((edge) => {
        const source = nodes.find((node) => node.id === edge.source);
        const connectedType =
          source && edge.sourceHandle ? this.graphOutputScalarType(source, edge.sourceHandle, parameters) : null;
        return connectedType === sourceScalarType;
      });
  }
}

export function triggerAlreadyExists(nodes: CanvasNode[], trigger: GraphTriggerDescriptor): boolean {
  return nodes.some((node) => node.type === GRAPH_NODE_TYPE.trigger && node.data.hook_name === trigger.hook_name);
}
