import { hasOnlyResponseFields } from "$lib/api/responseValidation/fields";
import { isOutcomePrice } from "$lib/outcomePrices";

import { isOptionalNullable } from "$lib/valueGuards";
import { isPositiveDecimal } from "$lib/decimalGuards";

import { isArrayOf, isFiniteNumber } from "$lib/valueGuards";

import runtimeContract from "$lib/runtimeContract.fixture.json";

import catalogContract from "$lib/catalog/catalogContract.fixture.json";

import { graphScalarValueIsValid as isScalarValue } from "$lib/catalog/scalarValue";

import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";

import { nodeGraphContractIsValid } from "$lib/catalog/runtimeGraphValidation";

import { isNonemptyString, isOneOf, isRecord } from "$lib/valueGuards";

const GRAPH_SCALAR_TYPES = Object.values(catalogContract.graphScalarType);

const GRAPH_COMPARISON_OPERATORS = Object.values(catalogContract.graphComparisonOperator);

const GRAPH_BROKER_ACTIONS = Object.values(catalogContract.graphBrokerAction);

export function isNodeGraph(value: unknown): boolean {
  if (!isRecord(value) || !Array.isArray(value.nodes) || value.nodes.length < catalogContract.nodeGraph.minimumNodes) {
    return false;
  }
  if (!value.nodes.every(isGraphNode)) return false;
  if (value.parameters !== undefined && (!Array.isArray(value.parameters) || !value.parameters.every(isGraphParameter)))
    return false;
  const edgesAreValid =
    value.edges === undefined ||
    (Array.isArray(value.edges) &&
      value.edges.every(
        (edge) =>
          isRecord(edge) &&
          isGraphEdgeIdentifier(edge.id) &&
          isGraphIdentifier(edge.source) &&
          isGraphIdentifier(edge.source_handle) &&
          isGraphIdentifier(edge.target) &&
          isGraphIdentifier(edge.target_handle),
      ));
  return edgesAreValid && nodeGraphContractIsValid(value as unknown as import("$lib/api/generated").NodeGraph);
}

export function isGraphCatalog(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !isArrayOf(value.triggers, isTriggerDescriptor) ||
    !isArrayOf(value.operations, isOperationDescriptor) ||
    !isArrayOf(value.constants, isConstantDescriptor) ||
    !isArrayOf(value.comparisons, isComparisonDescriptor) ||
    !isArrayOf(value.broker_actions, isBrokerActionDescriptor)
  )
    return false;
  return (
    hasUniqueValues(value.triggers, "hook_name") &&
    hasUniqueValues(value.operations, "operation") &&
    hasUniqueValues(value.constants, "scalar_type") &&
    hasUniqueValues(value.comparisons, "operator") &&
    hasUniqueValues(value.broker_actions, "action")
  );
}

export function isGraphPreviewResponse(value: Record<string, unknown>): boolean {
  return isArrayOf(value.nodes, isGraphPreviewNode) && isArrayOf(value.intended_orders, isIntendedOrder);
}

function isGraphNode(node: unknown): boolean {
  if (
    !isRecord(node) ||
    !isGraphIdentifier(node.id) ||
    !Object.values(GRAPH_NODE_TYPE).includes(node.type as never) ||
    !isRecord(node.position) ||
    !isGraphCoordinate(node.position.x) ||
    !isGraphCoordinate(node.position.y) ||
    !isRecord(node.data)
  )
    return false;
  switch (node.type) {
    case GRAPH_NODE_TYPE.parameter:
      return isGraphIdentifier(node.data.parameter_id);
    case GRAPH_NODE_TYPE.operation:
      return (
        catalogContract.graphNodeCatalog.operations
          .map((item) => item.operation)
          .includes(node.data.operation as never) &&
        (node.data.scalar_type === undefined || isOneOf(node.data.scalar_type, GRAPH_SCALAR_TYPES)) &&
        (node.data.input_ids === undefined ||
          (Array.isArray(node.data.input_ids) && node.data.input_ids.every(isGraphIdentifier)))
      );
    case GRAPH_NODE_TYPE.trigger:
      return isGraphHookName(node.data.hook_name);
    case GRAPH_NODE_TYPE.constant:
      return isConstantNodeData(node.data);
    case GRAPH_NODE_TYPE.comparison:
      return isOneOf(node.data.operator, GRAPH_COMPARISON_OPERATORS);
    case GRAPH_NODE_TYPE.brokerAction:
      return isOneOf(node.data.action, GRAPH_BROKER_ACTIONS);
    default:
      return false;
  }
}

function isConstantNodeData(data: Record<string, unknown>): boolean {
  if (!isOneOf(data.scalar_type, GRAPH_SCALAR_TYPES)) return false;
  return isScalarValue(data.scalar_type, data.value);
}

function isGraphIdentifier(value: unknown): value is string {
  return isTrimmedStringWithinLimit(value, catalogContract.nodeGraph.maximumIdentifierLength);
}

function isGraphEdgeIdentifier(value: unknown): value is string {
  return isTrimmedStringWithinLimit(value, catalogContract.nodeGraph.maximumEdgeIdentifierLength);
}

function isTrimmedStringWithinLimit(value: unknown, maximumLength: number): value is string {
  return (
    typeof value === "string" &&
    value === value.trim() &&
    value.length >= catalogContract.nodeGraph.minimumIdentifierLength &&
    value.length <= maximumLength
  );
}

function isGraphHookName(value: unknown): value is string {
  return isGraphIdentifier(value) && new RegExp(catalogContract.nodeGraph.hookNamePattern).test(value);
}

function isGraphCoordinate(value: unknown): value is number {
  return isFiniteNumber(value) && Math.abs(value) <= catalogContract.nodeGraph.coordinateLimit;
}

function hasUniqueValues(values: unknown, key: string): boolean {
  if (!Array.isArray(values) || !values.every(isRecord)) return false;
  const observed = values.map((value) => value[key]);
  return new Set(observed).size === observed.length;
}

function isTriggerDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.triggers.find(
    (descriptor) => descriptor.hook_name === value.hook_name,
  );
  return (
    canonicalDescriptor !== undefined &&
    value.node_type === canonicalDescriptor.node_type &&
    value.context_handle_id === canonicalDescriptor.context_handle_id &&
    value.context_type_name === canonicalDescriptor.context_type_name &&
    isGraphHookName(value.hook_name) &&
    (value.payload === undefined || value.payload === null || isGraphPayloadDescriptor(value.payload))
  );
}

function isGraphPayloadDescriptor(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNonemptyString(value.type_name) &&
    Array.isArray(value.fields) &&
    value.fields.every(isGraphPayloadField)
  );
}

function isConstantDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.constants.find(
    (descriptor) => descriptor.scalar_type === value.scalar_type,
  );
  return (
    canonicalDescriptor !== undefined &&
    value.node_type === canonicalDescriptor.node_type &&
    isNonemptyString(value.display_name) &&
    isOneOf(value.scalar_type, GRAPH_SCALAR_TYPES) &&
    isScalarValue(value.scalar_type, value.default_value) &&
    isRecord(value.output) &&
    isGraphOutputDescriptor(value.output)
  );
}

function isComparisonDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.comparisons.find(
    (descriptor) => descriptor.operator === value.operator,
  );
  return (
    isNonemptyString(value.display_name) &&
    isOneOf(value.operator, GRAPH_COMPARISON_OPERATORS) &&
    canonicalDescriptor !== undefined &&
    value.node_type === canonicalDescriptor.node_type &&
    Array.isArray(value.inputs) &&
    value.inputs.length === canonicalDescriptor.inputs.length &&
    value.inputs.every(isGraphInputDescriptor) &&
    isRecord(value.output) &&
    isGraphOutputDescriptor(value.output)
  );
}

function isBrokerActionDescriptor(value: Record<string, unknown>): boolean {
  const canonicalDescriptor = catalogContract.graphNodeCatalog.broker_actions.find(
    (descriptor) => descriptor.action === value.action,
  );
  return (
    canonicalDescriptor !== undefined &&
    value.node_type === canonicalDescriptor.node_type &&
    isNonemptyString(value.display_name) &&
    isOneOf(value.action, GRAPH_BROKER_ACTIONS) &&
    value.method_name === catalogContract.graphBrokerSubmitMethodName &&
    isOneOf(value.side, Object.values(runtimeContract.side)) &&
    Array.isArray(value.inputs) &&
    value.inputs.every(isGraphInputDescriptor)
  );
}

function isGraphInputDescriptor(value: unknown): boolean {
  return (
    isRecord(value) &&
    isGraphIdentifier(value.handle_id) &&
    isNonemptyString(value.display_name) &&
    Array.isArray(value.scalar_types) &&
    value.scalar_types.length >= catalogContract.nodeGraph.minimumInputScalarTypes &&
    value.scalar_types.every((type) => isOneOf(type, [...GRAPH_SCALAR_TYPES, catalogContract.contextPortType])) &&
    typeof value.nullable === "boolean" &&
    typeof value.required === "boolean"
  );
}

function isGraphOutputDescriptor(value: Record<string, unknown>): boolean {
  return (
    isGraphIdentifier(value.handle_id) &&
    isNonemptyString(value.display_name) &&
    isOneOf(value.scalar_type, [...GRAPH_SCALAR_TYPES, catalogContract.contextPortType]) &&
    (value.nullable === undefined || typeof value.nullable === "boolean")
  );
}

function isGraphFieldPathSegment(value: unknown): value is string {
  return isGraphIdentifier(value) && new RegExp(catalogContract.graphFieldPathSegmentPattern).test(value);
}

function isOperationDescriptor(value: Record<string, unknown>): boolean {
  return (
    catalogContract.graphNodeCatalog.operations.some((item) => item.operation === value.operation) &&
    isNonemptyString(value.display_name) &&
    isNonemptyString(value.category) &&
    isArrayOf(value.inputs, isGraphInputDescriptor) &&
    isArrayOf(value.outputs, isGraphOutputDescriptor)
  );
}

function isGraphPreviewNode(node: Record<string, unknown>): boolean {
  return (
    isGraphIdentifier(node.node_id) &&
    isOneOf(node.status, Object.values(catalogContract.graphValueStatus)) &&
    isOptionalNullable(node.reason, isGraphEvaluationReason) &&
    isRecord(node.outputs) &&
    Object.values(node.outputs).every(isGraphValueRead)
  );
}

export function isGraphValueRead(output: unknown): boolean {
  return (
    isRecord(output) &&
    hasOnlyResponseFields(output, "GraphValueRead") &&
    isOptionalNullable(output.input_handle_id, (handle) => typeof handle === "string") &&
    isOptionalNullable(output.message, (message) => typeof message === "string") &&
    isOneOf(output.status, Object.values(catalogContract.graphValueStatus)) &&
    (output.value === undefined ||
      output.value === null ||
      typeof output.value === "boolean" ||
      typeof output.value === "string") &&
    isOptionalNullable(output.reason, isGraphEvaluationReason)
  );
}

function isIntendedOrder(order: Record<string, unknown>): boolean {
  return (
    isNonemptyString(order.token_id) &&
    isOneOf(order.side, Object.values(runtimeContract.side)) &&
    isOutcomePrice(order.price) &&
    isPositiveDecimal(order.size)
  );
}

function isGraphPayloadField(field: unknown): boolean {
  return (
    isRecord(field) &&
    isGraphIdentifier(field.handle_id) &&
    isNonemptyString(field.display_name) &&
    isRecord(field.path) &&
    Array.isArray(field.path.segments) &&
    field.path.segments.length >= catalogContract.nodeGraph.minimumFieldPathSegments &&
    field.path.segments.every(isGraphFieldPathSegment) &&
    isNonemptyString(field.value_type) &&
    (field.scalar_type === null || isOneOf(field.scalar_type, GRAPH_SCALAR_TYPES)) &&
    typeof field.nullable === "boolean" &&
    typeof field.collection === "boolean" &&
    isRecord(field.value_schema)
  );
}

function isGraphParameter(parameter: unknown): boolean {
  return (
    isRecord(parameter) &&
    isGraphIdentifier(parameter.id) &&
    typeof parameter.name === "string" &&
    parameter.name.length > 0 &&
    parameter.name.length <= catalogContract.maximumParameterNameLength &&
    isRecord(parameter.data) &&
    isConstantNodeData(parameter.data)
  );
}

function isGraphEvaluationReason(value: unknown): boolean {
  return isOneOf(value, catalogContract.graphEvaluationReasons);
}
