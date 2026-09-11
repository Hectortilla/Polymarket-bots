export const RUN_DETAIL_COPY = {
  LIVE_DATA: "Live data",
  TABS_LABEL: "Run views",
  SHOW_EVENTS: "Show events",
  HIDE_EVENTS: "Hide events",
  NOT_FOUND: "Run not found. Older history may have expired; return to your workspace for retained runs.",
  RUN_LOAD_ERROR: "The run could not be loaded.",
  STREAM_RECONNECTING: "Live updates are unavailable. Reconnecting…",
  STOP_ERROR: "The stop request could not be sent.",
  SENDING: "Sending…",
  LOAD_EARLIER: "Load earlier events",
  LOAD_EARLIER_DASHBOARD: "Load earlier chart data",
  LOAD_ERROR: "Older durable events could not be loaded.",
  LOADING: "Loading…",
  NO_PROGRESS_EVENTS: "No trades, settlements, warnings, errors, or run status changes in the loaded history.",
  NO_DIAGNOSTIC_EVENTS: "No events in the loaded history.",
  SHOW_DIAGNOSTICS: "Show diagnostics",
  EVENTS_DESCRIPTION:
    "Trades, settlements, warnings, errors, and run status changes. Enable diagnostics for routine activity.",

  BOT_DELETED: "Bot configuration deleted",
  BOT_CONFIGURATION: "Bot configuration",
  EXECUTED_GRAPH: "Executed graph",
  CONFIGURATION_LAYOUT_ERROR: "The configuration layout is unavailable. Saved values are shown below.",
  GRAPH_LOAD_ERROR: "The executed graph could not be displayed.",
} as const;

export function loadedEventsLabel(count: number): string {
  return `${count} events loaded`;
}
