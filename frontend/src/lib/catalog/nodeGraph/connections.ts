import type { GraphNodeCatalog, GraphParameter } from "$lib/api/generated";

import { type Connection } from "@xyflow/svelte";

import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";

import { type CanvasEdge, type CanvasNode, hasCompleteHandles } from "$lib/catalog/nodeGraph/contracts";

import { graphOutputScalarType, inputsForNode } from "$lib/catalog/nodeGraph/ports";

export function connectionIsValid(
  connection: Connection | CanvasEdge,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  catalog: GraphNodeCatalog,
  parameters: GraphParameter[] = [],
): boolean {
  if (!hasCompleteHandles(connection)) return false;
  if (edges.some((edge) => edge.target === connection.target && edge.targetHandle === connection.targetHandle)) {
    return false;
  }
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target || source.id === target.id) return false;
  const sourceScalarType = graphOutputScalarType(source, connection.sourceHandle, catalog, parameters);
  const acceptedScalarTypes = inputScalarTypes(target, connection.targetHandle, catalog);
  if (
    target.type === GRAPH_NODE_TYPE.comparison &&
    !comparisonInputsMatchSourceType(target.id, sourceScalarType, nodes, edges, catalog, parameters)
  )
    return false;
  return sourceScalarType !== null && acceptedScalarTypes.includes(sourceScalarType);
}

function inputScalarTypes(node: CanvasNode, handleId: string, catalog: GraphNodeCatalog) {
  return inputsForNode(node, catalog).find((input) => input.handle_id === handleId)?.scalar_types ?? [];
}

function comparisonInputsMatchSourceType(
  targetNodeId: string,
  sourceScalarType: ReturnType<typeof graphOutputScalarType>,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  catalog: GraphNodeCatalog,
  parameters: GraphParameter[],
): boolean {
  return edges
    .filter((edge) => edge.target === targetNodeId)
    .every((edge) => {
      const source = nodes.find((node) => node.id === edge.source);
      const connectedType =
        source && edge.sourceHandle ? graphOutputScalarType(source, edge.sourceHandle, catalog, parameters) : null;
      return connectedType === sourceScalarType;
    });
}
