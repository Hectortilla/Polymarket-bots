export const HOME_COPY = {
  CONFIGURED_BOTS: 'Configured bots',
  CREATE_FIRST_BOT: 'Create your first bot.',
  NOT_RUN_YET: 'Not run yet',
  RECENT_RUNS: 'Recent runs',
  LOAD_ERROR: 'The control plane could not be loaded.'
} as const;

export const HOME_COLUMN_LABEL = {
  BOT_AND_MARKETS: 'Bot and markets',
  CREATED: 'Created',
  ENDED: 'Ended',
  EQUITY: 'Equity',
  GRAPH: 'Graph',
  LATEST_RUN: 'Latest run',
  MAX_ORDER: 'Max order',
  RUN: 'Run',
  STATUS: 'Status',
  UPDATED: 'Updated'
} as const;

export function botRowLabel(name: string): string {
  return `Open ${name}`;
}

export function runRowLabel(name: string, createdAtLabel: string): string {
  return `Open run for ${name} created ${createdAtLabel}`;
}

export function graphRevisionLabel(revision: number): string {
  return `revision ${revision}`;
}
