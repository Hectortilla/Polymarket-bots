import type {
  GraphNodeCatalog,
  GraphParameter,
  GraphOperationDescriptor,
  GraphTriggerDescriptor,
  GraphConstantDescriptor,
  GraphComparisonDescriptor,
  GraphBrokerActionDescriptor,
} from "$lib/api/generated";
import { SIDE } from "$lib/sides";
import { GRAPH_NODE_TYPE, GRAPH_SCALAR_TYPE } from "$lib/catalog/graphContracts";
import { GRAPH_NODE_COPY } from "$lib/catalog/copy";
import { triggerAlreadyExists } from "$lib/catalog/nodeGraph/catalog";
import type { CanvasNode } from "$lib/catalog/nodeGraph/contracts";

type NodeCategory = (typeof GRAPH_NODE_TYPE)[keyof typeof GRAPH_NODE_TYPE];
type PaletteIcon = "trigger" | "boolean" | "number" | "string" | "comparison" | "buy" | "sell";

export type PaletteItem = {
  id: string;
  category: NodeCategory;
  subgroup?: string;
  icon: PaletteIcon;
  name: string;
  description: string;
  meta: string;
  searchTerms: string;
  disabled: boolean;
  select: () => void;
};

export type PaletteActions = {
  onaddoperation: (operation: GraphOperationDescriptor) => void;
  onaddparameter: (parameter: GraphParameter) => void;
  onaddtrigger: (trigger: GraphTriggerDescriptor) => void;
  onaddconstant: (constant: GraphConstantDescriptor) => void;
  onaddcomparison: (comparison: GraphComparisonDescriptor) => void;
  onaddaction: (action: GraphBrokerActionDescriptor) => void;
};

export function paletteItems(
  catalog: GraphNodeCatalog,
  nodes: CanvasNode[],
  parameters: GraphParameter[],
  additionDisabled: boolean,
  actions: PaletteActions,
): PaletteItem[] {
  const { onaddoperation, onaddparameter, onaddtrigger, onaddconstant, onaddcomparison, onaddaction } = actions;
  return [
    ...(catalog.operations ?? []).map((operation) => ({
      id: operation.operation,
      category: GRAPH_NODE_TYPE.operation,
      subgroup: operation.category,
      icon: "comparison" as const,
      name: operation.display_name,
      description: operation.category,
      meta: operation.category,
      searchTerms: `${operation.display_name} ${operation.operation} ${operation.category}`,
      disabled: additionDisabled,
      select: () => onaddoperation(operation),
    })),
    ...parameters.map((parameter) => ({
      id: parameter.id,
      category: GRAPH_NODE_TYPE.parameter,
      icon: "number" as const,
      name: parameter.name,
      description: "Named strategy parameter",
      meta: parameter.data.scalar_type,
      searchTerms: parameter.name,
      disabled: additionDisabled,
      select: () => onaddparameter(parameter),
    })),
    ...catalog.triggers.map((trigger) => ({
      id: `trigger-${trigger.hook_name}`,
      category: GRAPH_NODE_TYPE.trigger,
      icon: "trigger" as const,
      name: trigger.hook_name,
      description: trigger.payload
        ? `Start with ${trigger.payload.type_name} data.`
        : "Start from a bot lifecycle event.",
      meta: "event",
      searchTerms: `${trigger.hook_name} ${trigger.payload?.type_name ?? ""}`,
      disabled: additionDisabled || triggerAlreadyExists(nodes, trigger),
      select: () => onaddtrigger(trigger),
    })),
    ...catalog.constants.map((constant) => ({
      id: `constant-${constant.scalar_type}`,
      category: GRAPH_NODE_TYPE.constant,
      icon: constantIcon(constant),
      name: constant.display_name,
      description: `Use ${constant.scalar_type} as an input value.`,
      meta: constant.scalar_type,
      searchTerms: `${constant.display_name} ${constant.scalar_type}`,
      disabled: additionDisabled,
      select: () => onaddconstant(constant),
    })),
    ...comparisonPaletteItems(catalog.comparisons, onaddcomparison).map((item) => ({
      ...item,
      disabled: additionDisabled || item.disabled,
    })),
    ...catalog.broker_actions.map((action) => ({
      id: `action-${action.action}`,
      category: GRAPH_NODE_TYPE.brokerAction,
      icon: actionIcon(action),
      name: action.display_name,
      description: `Submit a ${action.side} order through Broker.${action.method_name}.`,
      meta: action.side,
      searchTerms: `${action.display_name} ${action.action} ${action.side} ${action.method_name}`,
      disabled: additionDisabled,
      select: () => onaddaction(action),
    })),
  ];
}

function comparisonPaletteItems(
  comparisons: GraphComparisonDescriptor[],
  onaddcomparison: PaletteActions["onaddcomparison"],
): PaletteItem[] {
  const defaultComparison = comparisons[0];
  if (!defaultComparison) return [];
  const operatorCount = comparisons.length;

  return [
    {
      id: "comparison",
      category: GRAPH_NODE_TYPE.comparison,
      icon: "comparison",
      name: GRAPH_NODE_COPY.COMPARISON,
      description: "Compare two compatible values with a selectable operator.",
      meta: `${operatorCount} ${operatorCount === 1 ? "operator" : "operators"}`,
      searchTerms: [
        "comparison",
        "logic",
        ...comparisons.flatMap((comparison) => [comparison.display_name, comparison.operator]),
      ].join(" "),
      disabled: false,
      select: () => onaddcomparison(defaultComparison),
    },
  ];
}

function constantIcon(constant: GraphConstantDescriptor): PaletteIcon {
  switch (constant.scalar_type) {
    case GRAPH_SCALAR_TYPE.boolean:
      return "boolean";
    case GRAPH_SCALAR_TYPE.number:
      return "number";
    case GRAPH_SCALAR_TYPE.string:
      return "string";
  }
}

function actionIcon(action: GraphBrokerActionDescriptor): PaletteIcon {
  switch (action.side) {
    case SIDE.buy:
      return "buy";
    case SIDE.sell:
      return "sell";
  }
}
