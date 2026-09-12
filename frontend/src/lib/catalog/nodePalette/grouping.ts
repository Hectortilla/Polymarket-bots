import { PALETTE_CATEGORY_COPY } from "./copy";
import { GRAPH_NODE_TYPE } from "$lib/catalog/graphContracts";
import type { PaletteItem } from "./items";

const categories = [
  {
    id: GRAPH_NODE_TYPE.operation,
    label: PALETTE_CATEGORY_COPY.OPERATIONS,
    description: "Calculate, control signals, query your portfolio, and inspect results.",
  },
  {
    id: GRAPH_NODE_TYPE.parameter,
    label: "Parameters",
    description: "Reuse named strategy settings.",
  },
  {
    id: GRAPH_NODE_TYPE.trigger,
    label: "Triggers",
    description: "Start a branch from a runtime event.",
  },
  {
    id: GRAPH_NODE_TYPE.constant,
    label: PALETTE_CATEGORY_COPY.VALUES,
    description: "Supply a typed value to another node.",
  },
  {
    id: GRAPH_NODE_TYPE.comparison,
    label: "Comparisons",
    description: "Compare compatible values.",
  },
  {
    id: GRAPH_NODE_TYPE.brokerAction,
    label: "Actions",
    description: "Submit a fixed-side paper order.",
  },
] as const satisfies ReadonlyArray<{
  id: PaletteItem["category"];
  label: string;
  description: string;
}>;

export function visiblePaletteGroups(items: PaletteItem[], normalizedQuery: string) {
  return categories
    .map((category) => ({
      ...category,
      items: items.filter(
        (item) => item.category === category.id && item.searchTerms.toLocaleLowerCase().includes(normalizedQuery),
      ),
    }))
    .filter((category) => category.items.length > 0);
}

export function operationGroups(items: PaletteItem[]) {
  return [...new Set(items.map((item) => item.subgroup!))].map((label) => ({
    id: `${GRAPH_NODE_TYPE.operation}-${encodeURIComponent(label)}`,
    label,
    items: items.filter((item) => item.subgroup === label),
  }));
}
