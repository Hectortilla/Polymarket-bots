import runtimeContract from "$lib/runtimeContract.fixture.json";

export const BOT_DETAIL_COPY = {
  EXPIRED_LAUNCH:
    "The previous launch cannot be recovered. Its history may have expired, or the request never arrived. Review retained history before choosing Run again to start a new run.",
  DELETE: "Delete bot",
  DELETE_CONFIRM: "Confirm deletion",
  DELETE_CANCEL: "Cancel",
  DELETING: "Deleting…",
  DELETE_DESCRIPTION:
    "This bot will disappear from your configurations. Its saved data stays in the system and past runs remain in your history. Stop all active runs and wait for them to finish before deleting. Unsaved changes will be discarded.",
  DELETE_ACTIVE_RUNS: runtimeContract.botDeletion.activeRunsDetail,
  DELETE_ERROR: "The bot could not be deleted. Please try again.",
  CONFIG_SAVE_ERROR: "The bot configuration could not be saved.",
  GRAPH_SAVE_ERROR: "The graph revision could not be saved.",
  LOAD_ERROR: "The saved bot could not be loaded.",
  NOT_FOUND: "Bot not found.",
  RUN: "Run bot",
  RUN_ERROR:
    "The launch result could not be confirmed. Retry to recover the same run; reload also preserves this attempt.",
  SAVE_CHANGES: "Save changes",
  SAVED: "saved",
  SAVING_CHANGES: "Saving changes",
  STARTING: "Starting...",
  UNSAVED: "unsaved changes",
  UNSAVED_RUN_BLOCK: "Save your changes before starting a run.",
} as const;

export function botGraphRevisionLabel(revision: number | null | undefined): string {
  return `Bot graph revision ${revision}`;
}
