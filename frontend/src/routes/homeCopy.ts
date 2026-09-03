export const HOME_COPY = {
  LOAD_ERROR: 'The control plane could not be loaded.',
  NO_SAVED_BOTS: 'No saved bots yet. Choose a definition above to create one.',
  OPERATIONS: 'Paper operations',
  RECENT_TERMINAL_RUNS: 'Recent terminal runs',
  SAVED_BOTS: 'Saved bots'
} as const;

export const HOME_COLUMN_LABEL = {
  BOT: 'Bot',
  CREATED: 'Created',
  DEFINITION: 'Definition',
  ENDED: 'Ended',
  EQUITY: 'Equity',
  GRAPH: 'Graph',
  RUN: 'Run',
  STATUS: 'Status',
  UPDATED: 'Updated'
} as const;

export function graphRevisionLabel(revision: number): string {
  return `revision ${revision}`;
}
