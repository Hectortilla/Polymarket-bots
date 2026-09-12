import { isRecord, isArrayOf, isNonemptyString, isOneOf } from "$lib/valueGuards";
import { hasOnlyResponseFields } from "../fields";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { graphScalarValueIsValid as isScalarValue } from "$lib/catalog/scalarValue";
import {
  GRAPH_SCALAR_TYPES,
  GRAPH_COMPARISON_OPERATORS,
  GRAPH_BROKER_ACTIONS,
  isGraphIdentifier,
  isGraphHookName,
  isGraphFieldPathSegment,
  hasUniqueValues,
} from "./primitives";

export function isGraphCatalog(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphNodeCatalog")) return false;
  if (
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

function isTriggerDescriptor(value: Record<string, unknown>): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphTriggerDescriptor")) return false;
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
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphPayloadDescriptor")) return false;
  return isNonemptyString(value.type_name) && Array.isArray(value.fields) && value.fields.every(isGraphPayloadField);
}

function isConstantDescriptor(value: Record<string, unknown>): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphConstantDescriptor")) return false;
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
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphComparisonDescriptor")) return false;
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
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphBrokerActionDescriptor")) return false;
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
    value.inputs.every(isGraphInputDescriptor) &&
    (value.outputs === undefined || isArrayOf(value.outputs, isGraphOutputDescriptor))
  );
}

function isGraphInputDescriptor(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphInputDescriptor")) return false;
  return (
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
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphOutputDescriptor")) return false;
  return (
    isGraphIdentifier(value.handle_id) &&
    isNonemptyString(value.display_name) &&
    isOneOf(value.scalar_type, [...GRAPH_SCALAR_TYPES, catalogContract.contextPortType]) &&
    (value.nullable === undefined || typeof value.nullable === "boolean")
  );
}

function isOperationDescriptor(value: Record<string, unknown>): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphOperationDescriptor")) return false;
  return (
    catalogContract.graphNodeCatalog.operations.some((item) => item.operation === value.operation) &&
    isNonemptyString(value.display_name) &&
    isNonemptyString(value.category) &&
    isArrayOf(value.inputs, isGraphInputDescriptor) &&
    isArrayOf(value.outputs, isGraphOutputDescriptor)
  );
}

function isGraphPayloadField(field: unknown): boolean {
  if (!isRecord(field) || !hasOnlyResponseFields(field, "GraphFieldDescriptor")) return false;
  return (
    isGraphIdentifier(field.handle_id) &&
    isNonemptyString(field.display_name) &&
    isRecord(field.path) &&
    hasOnlyResponseFields(field.path, "GraphFieldPath") &&
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
