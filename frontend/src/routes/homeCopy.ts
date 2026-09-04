export const HOME_COPY = {
  LOAD_ERROR: 'The control plane could not be loaded.'
} as const;

export const HOME_COLUMN_LABEL = {
  CREATED: 'Created',
  ENDED: 'Ended',
  EQUITY: 'Equity',
  RUN: 'Run',
  STATUS: 'Status'
} as const;

export function graphRevisionLabel(revision: number): string {
  return `revision ${revision}`;
}
