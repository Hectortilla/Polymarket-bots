import { isRecord } from "$lib/valueGuards";
import { hasOnlyResponseFields } from "../fields";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";
import { nodeGraphContractIsValid } from "$lib/catalog/runtimeGraphValidation";
import { isGraphNode, isGraphParameter } from "./nodes";
import { isGraphEdgeIdentifier, isGraphIdentifier } from "./primitives";

export function isNodeGraph(value: unknown): boolean {
  if (!isRecord(value) || !hasOnlyResponseFields(value, "NodeGraph")) return false;
  if (!Array.isArray(value.nodes) || value.nodes.length < catalogContract.nodeGraph.minimumNodes) {
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
          hasOnlyResponseFields(edge, "GraphEdge") &&
          isGraphEdgeIdentifier(edge.id) &&
          isGraphIdentifier(edge.source) &&
          isGraphIdentifier(edge.source_handle) &&
          isGraphIdentifier(edge.target) &&
          isGraphIdentifier(edge.target_handle),
      ));
  return edgesAreValid && nodeGraphContractIsValid(value as unknown as import("$lib/api/generated").NodeGraph);
}
