import { isRecord, isOneOf } from "$lib/valueGuards";
import { hasOnlyResponseFields } from "../fields";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";
import { graphScalarValueIsValid as isScalarValue } from "$lib/catalog/scalarValue";
import {
  GRAPH_SCALAR_TYPES,
  GRAPH_COMPARISON_OPERATORS,
  GRAPH_BROKER_ACTIONS,
  isGraphIdentifier,
  isGraphCoordinate,
  isGraphHookName,
} from "./primitives";

export function isGraphNode(node: unknown): boolean {
  if (
    !isRecord(node) ||
    !isGraphIdentifier(node.id) ||
    !Object.values(GRAPH_NODE_TYPE).includes(node.type as never) ||
    !isRecord(node.position) ||
    !hasOnlyResponseFields(node.position, "GraphPosition") ||
    !isGraphCoordinate(node.position.x) ||
    !isGraphCoordinate(node.position.y) ||
    !isRecord(node.data)
  )
    return false;
  switch (node.type) {
    case GRAPH_NODE_TYPE.parameter:
      if (!hasOnlyResponseFields(node, "GraphParameterNode")) return false;
      if (!hasOnlyResponseFields(node.data, "GraphParameterNodeData")) return false;
      return isGraphIdentifier(node.data.parameter_id);
    case GRAPH_NODE_TYPE.operation:
      if (!hasOnlyResponseFields(node, "GraphOperationNode")) return false;
      if (!hasOnlyResponseFields(node.data, "GraphOperationNodeData")) return false;
      return (
        catalogContract.graphNodeCatalog.operations
          .map((item) => item.operation)
          .includes(node.data.operation as never) &&
        (node.data.scalar_type === undefined || isOneOf(node.data.scalar_type, GRAPH_SCALAR_TYPES)) &&
        (node.data.input_ids === undefined ||
          (Array.isArray(node.data.input_ids) && node.data.input_ids.every(isGraphIdentifier)))
      );
    case GRAPH_NODE_TYPE.trigger:
      if (!hasOnlyResponseFields(node, "GraphTriggerNode")) return false;
      if (!hasOnlyResponseFields(node.data, "GraphTriggerNodeData")) return false;
      return isGraphHookName(node.data.hook_name);
    case GRAPH_NODE_TYPE.constant:
      if (!hasOnlyResponseFields(node, "GraphConstantNode")) return false;
      return isConstantNodeData(node.data);
    case GRAPH_NODE_TYPE.comparison:
      if (!hasOnlyResponseFields(node, "GraphComparisonNode")) return false;
      if (!hasOnlyResponseFields(node.data, "GraphComparisonNodeData")) return false;
      return isOneOf(node.data.operator, GRAPH_COMPARISON_OPERATORS);
    case GRAPH_NODE_TYPE.brokerAction:
      if (!hasOnlyResponseFields(node, "GraphBrokerActionNode")) return false;
      if (!hasOnlyResponseFields(node.data, "GraphBrokerActionNodeData")) return false;
      return isOneOf(node.data.action, GRAPH_BROKER_ACTIONS);
    default:
      return false;
  }
}

export function isGraphParameter(parameter: unknown): boolean {
  if (!isRecord(parameter) || !hasOnlyResponseFields(parameter, "GraphParameter")) return false;
  return (
    isGraphIdentifier(parameter.id) &&
    typeof parameter.name === "string" &&
    parameter.name.length > 0 &&
    parameter.name.length <= catalogContract.maximumParameterNameLength &&
    isRecord(parameter.data) &&
    isConstantNodeData(parameter.data)
  );
}

function isConstantNodeData(data: Record<string, unknown>): boolean {
  if (!isOneOf(data.scalar_type, GRAPH_SCALAR_TYPES)) return false;
  const constantDataModelByScalarType = {
    [catalogContract.graphScalarType.BOOLEAN]: "GraphBooleanConstantData",
    [catalogContract.graphScalarType.NUMBER]: "GraphNumberConstantData",
    [catalogContract.graphScalarType.STRING]: "GraphStringConstantData",
  } as const;
  return (
    hasOnlyResponseFields(data, constantDataModelByScalarType[data.scalar_type]) &&
    isScalarValue(data.scalar_type, data.value)
  );
}
