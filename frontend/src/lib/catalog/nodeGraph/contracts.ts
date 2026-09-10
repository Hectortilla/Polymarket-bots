import type {
  GraphBrokerActionNode,
  GraphBrokerActionNodeData,
  GraphComparisonNode,
  GraphComparisonNodeData,
  GraphConstantNode,
  GraphConstantNodeData,
  GraphNode,
  GraphOperationNode,
  GraphParameterNode,
  GraphTriggerNode,
  GraphTriggerNodeData,
} from "$lib/api/generated";

import { type Connection, type Edge, type Node } from "@xyflow/svelte";

type GraphNodeData = GraphNode["data"];

export type CanvasNode =
  | Node<GraphTriggerNodeData, GraphTriggerNode["type"]>
  | Node<GraphConstantNodeData, GraphConstantNode["type"]>
  | Node<GraphComparisonNodeData, GraphComparisonNode["type"]>
  | Node<GraphOperationNode["data"], GraphOperationNode["type"]>
  | Node<GraphParameterNode["data"], GraphParameterNode["type"]>
  | Node<GraphBrokerActionNodeData, GraphBrokerActionNode["type"]>;

export type CanvasEdge = Edge;

export function hasCompleteHandles(connection: Connection | CanvasEdge): connection is (Connection | CanvasEdge) & {
  sourceHandle: string;
  targetHandle: string;
} {
  return Boolean(connection.sourceHandle && connection.targetHandle);
}
