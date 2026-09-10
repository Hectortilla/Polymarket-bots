import contract from "$lib/runtimeContract.fixture.json" with { type: "json" };

export const LIFECYCLE_COPY = {
  AMBIGUOUS_RESPONSE:
    "The deletion response was not received. Your request may have completed. Try signing in again before retrying; revoked access may mean deletion was accepted.",
  DELETE_HEADING: "Delete account and data",
  DELETE: "Request permanent deletion",
  CONFIRM: "I understand that my bots and history will be permanently removed.",
  PASSWORD: "Current password for account deletion",
  REQUESTED: `Deletion requested. Access is revoked and paper runs are stopped. Eligible account data is removed within ${contract.dataLifecycle.deletionTargetHours} hours.`,
  HISTORY: `History keeps up to ${contract.resourcePolicy.retained_runs} completed runs for ${contract.resourcePolicy.history_retention_days} days after completion. Older runs and their events expire; active runs and saved bots are preserved.`,
} as const;
