export const HOME_COPY = {
  CONFIGURED_BOTS: "Bot configurations",
  CREATE_FIRST_BOT: "Create your first bot.",
  NOT_RUN_YET: "Not run yet",
  RECENT_RUNS: "Runs",
  LOAD_ERROR: "The control plane could not be loaded.",
} as const;

export const HOME_COLUMN_LABEL = {
  BOT_AND_MARKETS: "Bot and markets",
  BOT_NAME: "Bot name",
  EQUITY: "Equity",
  LATEST_RUN: "Latest run",
  STATUS: "Status",
} as const;

export function botRowLabel(name: string): string {
  return `Open ${name}`;
}

export function runRowLabel(name: string, createdAtLabel: string): string {
  return `Open run for ${name} created ${createdAtLabel}`;
}
