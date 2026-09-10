export const RUN_DETAIL_COPY = {
  NOT_FOUND: "Run not found. Older history may have expired; return to your workspace for retained runs.",
  RUN_LOAD_ERROR: "The run could not be loaded.",
  STREAM_RECONNECTING: "Live updates are unavailable. Reconnecting…",
  STOP_ERROR: "The stop request could not be sent.",
  SENDING: "Sending…",
  LOAD_EARLIER: "Load earlier events",
  LOAD_ERROR: "Older durable events could not be loaded.",
  LOADING: "Loading…",
  NO_PROGRESS_EVENTS: "No progress events in the loaded history.",

  BOT_DELETED: "Bot configuration deleted",
  BOT_CONFIGURATION: "Bot configuration",
  EXECUTED_GRAPH_REVISION: "Executed graph revision",
  GRAPH_REVISION: "graph revision",
  GRAPH_LOAD_ERROR: "The executed graph could not be displayed.",
} as const;

export function runGraphRevisionLabel(revision: number | null | undefined): string {
  return `${RUN_DETAIL_COPY.GRAPH_REVISION} ${revision}`;
}

export function executedRunGraphRevisionLabel(revision: number | null | undefined): string {
  return `${RUN_DETAIL_COPY.EXECUTED_GRAPH_REVISION} ${revision}`;
}

export function loadedEventsLabel(count: number): string {
  return `${count} events loaded`;
}
