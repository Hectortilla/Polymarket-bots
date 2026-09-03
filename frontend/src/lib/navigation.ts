export const NAVIGATION_PATH = {
  HOME: '/',
  GRAPH_TEMPLATES: '/graph-templates'
} as const;

export const NAVIGATION_LABEL = {
  BACK_TO_CATALOG: 'Back to catalog',
  BACK_TO_OPERATIONS: 'Back to operations',
  GRAPH_TEMPLATES: 'Graph templates'
} as const;

export function botPath(botId: string): string {
  return `/bots/${botId}`;
}

export function launchPath(definitionId: string): string {
  return `/launch/${definitionId}`;
}

export function runPath(runId: string): string {
  return `/runs/${runId}`;
}
