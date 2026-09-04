export const BOT_DETAIL_COPY = {
  CONFIG_SAVE_ERROR: 'The bot configuration could not be saved.',
  GRAPH_SAVE_ERROR: 'The graph revision could not be saved.',
  LOAD_ERROR: 'The saved bot could not be loaded.',
  NOT_FOUND: 'Bot not found.',
  RUN: 'Run bot',
  RUN_ERROR: 'The bot run could not be started.',
  SAVE_CHANGES: 'Save changes',
  SAVED: 'saved',
  SAVING_CHANGES: 'Saving changes',
  STARTING: 'Starting...',
  UNSAVED: 'unsaved changes',
  UNSAVED_RUN_BLOCK: 'Save your changes before starting a run.'
} as const;

export function botGraphRevisionLabel(
  revision: number | null | undefined
): string {
  return `Bot graph revision ${revision}`;
}
