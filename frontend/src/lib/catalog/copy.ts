export const LAUNCH_FORM_COPY = { SAVE_BOT: "Save bot", SAVING: "Saving…" } as const;

export const GRAPH_FIELD_COPY = {
  PARAMETER_VALUE: "Parameter value",
  COMPARISON_OPERATOR: "Comparison operator",
  PARAMETER_TYPE: "Parameter type",

  VALUE_TYPE: "Value type",
  VALUE: "Value",
  OPERATOR: "Operator",
  INVALID_NUMBER: "Enter a finite Number within the supported range.",
} as const;

export const GRAPH_PREVIEW_COPY = {
  AVAILABLE_CASH: "Available cash",
  SAMPLE_EVENT: "Sample event",
  SAMPLE_POSITIONS: "Sample positions",
  UNAVAILABLE: "Unavailable",

  PREVIEW: "Preview decisions",
  BUSY: "Evaluating…",
  NODE_RESULTS: "Node results",
  INTENDED_ORDERS: "Intended orders",
  NO_ORDER: "No order requested for this sample.",
  ERROR: "Preview failed. Check the sample inputs.",
} as const;

export const GRAPH_NODE_COPY = { COMPARISON: "Comparison" } as const;

export const MARKET_SELECTOR_COPY = {
  PLACEHOLDER: "Search markets by name, topic, or ID…",
  NO_RESULTS: "No available markets found. Try a different name, topic, or ID.",

  SEARCH_ERROR: "Search is unavailable. Please try again.",
  UNAVAILABLE: "No longer available for trading",
  MISSING: "Market not found — remove or replace this selection",
  LOOKUP_ERROR: "Selected market details could not be loaded. Your selections are preserved.",
} as const;

export function intendedOrdersLabel(count: number): string {
  return `${GRAPH_PREVIEW_COPY.INTENDED_ORDERS} (${count})`;
}
