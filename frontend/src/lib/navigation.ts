export const NAVIGATION_PATH = {
  HOME: '/',
  NEW_BOT: '/bots/new'
} as const;

export const NAVIGATION_LABEL = {
  BACK_TO_BOTS: 'Back to bots',
  BOTS: 'Bots',
  NEW_BOT: 'New bot'
} as const;

export function botPath(botId: string): string {
  return `/bots/${botId}`;
}

export function runPath(runId: string): string {
  return `/runs/${runId}`;
}
