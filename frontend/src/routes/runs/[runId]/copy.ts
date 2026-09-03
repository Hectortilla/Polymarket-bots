export const RUN_DETAIL_COPY = {
  EXECUTED_GRAPH_REVISION: 'Executed graph revision',
  GRAPH_REVISION: 'graph revision',
  GRAPH_LOAD_ERROR: 'The executed graph could not be displayed.'
} as const;

export function runGraphRevisionLabel(
  revision: number | null | undefined
): string {
  return `${RUN_DETAIL_COPY.GRAPH_REVISION} ${revision}`;
}

export function executedRunGraphRevisionLabel(
  revision: number | null | undefined
): string {
  return `${RUN_DETAIL_COPY.EXECUTED_GRAPH_REVISION} ${revision}`;
}
