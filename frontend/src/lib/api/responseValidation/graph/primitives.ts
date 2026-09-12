import { isFiniteNumber, isRecord } from "$lib/valueGuards";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";

export const GRAPH_SCALAR_TYPES = Object.values(catalogContract.graphScalarType);
export const GRAPH_COMPARISON_OPERATORS = Object.values(catalogContract.graphComparisonOperator);
export const GRAPH_BROKER_ACTIONS = Object.values(catalogContract.graphBrokerAction);

export function isGraphIdentifier(value: unknown): value is string {
  return isTrimmedStringWithinLimit(value, catalogContract.nodeGraph.maximumIdentifierLength);
}

export function isGraphEdgeIdentifier(value: unknown): value is string {
  return isTrimmedStringWithinLimit(value, catalogContract.nodeGraph.maximumEdgeIdentifierLength);
}

export function isGraphHookName(value: unknown): value is string {
  return isGraphIdentifier(value) && new RegExp(catalogContract.nodeGraph.hookNamePattern).test(value);
}

export function isGraphCoordinate(value: unknown): value is number {
  return isFiniteNumber(value) && Math.abs(value) <= catalogContract.nodeGraph.coordinateLimit;
}

export function isGraphFieldPathSegment(value: unknown): value is string {
  return isGraphIdentifier(value) && new RegExp(catalogContract.graphFieldPathSegmentPattern).test(value);
}

export function hasUniqueValues(values: unknown, key: string): boolean {
  if (!Array.isArray(values) || !values.every(isRecord)) return false;
  const observed = values.map((value) => value[key]);
  return new Set(observed).size === observed.length;
}

function isTrimmedStringWithinLimit(value: unknown, maximumLength: number): value is string {
  return (
    typeof value === "string" &&
    value === value.trim() &&
    value.length >= catalogContract.nodeGraph.minimumIdentifierLength &&
    value.length <= maximumLength
  );
}
