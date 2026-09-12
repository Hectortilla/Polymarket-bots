import { isRecord, isArrayOf, isNonemptyString, isOneOf, isOptionalNullable } from "$lib/valueGuards";
import { hasOnlyResponseFields } from "../fields";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { isOutcomePrice } from "$lib/outcomePrices";
import { isPositiveDecimal } from "$lib/decimalGuards";
import { isGraphIdentifier } from "./primitives";

export function isGraphPreviewResponse(value: Record<string, unknown>): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "GraphPreviewResponse")) return false;
  return isArrayOf(value.nodes, isGraphPreviewNode) && isArrayOf(value.intended_orders, isIntendedOrder);
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

function isGraphPreviewNode(node: Record<string, unknown>): boolean {
  if (!isRecord(node) || !hasOnlyResponseFields(node, "GraphNodeEvaluationRead")) return false;
  return (
    isGraphIdentifier(node.node_id) &&
    isOneOf(node.status, Object.values(catalogContract.graphValueStatus)) &&
    isOptionalNullable(node.reason, isGraphEvaluationReason) &&
    isRecord(node.outputs) &&
    Object.values(node.outputs).every(isGraphValueRead)
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

function isGraphEvaluationReason(value: unknown): boolean {
  return isOneOf(value, catalogContract.graphEvaluationReasons);
}
