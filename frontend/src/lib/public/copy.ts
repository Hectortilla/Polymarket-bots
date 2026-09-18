import contract from "$lib/runtimeContract.fixture.json" with { type: "json" };

export const PUBLIC_COPY = {
  SUPPORT: "Support",
  DATA_POLICY: "privacy policy",
  RECOVER: "Reset your password",
  SIMULATION:
    "All runs use simulated funds. No real orders are placed and no money moves. Simulated fills and returns may differ from live trading results.",
  SAVE_BEFORE_RUN:
    "Review your settings and save the bot. Saving does not start it. Open the saved bot and select Run bot.",
  ACCOUNT_DATA:
    "We store your email, a password hash, sign-in and recovery records, and email verification status to manage your account. A session cookie keeps you signed in. We also store your bot settings, strategy graphs and revisions, selected market and wallet identifiers, and run history. Your bots and runs are private to your account.",
  RESTORE_QUARANTINE:
    "If a backup is restored, deletion requests must be reapplied before access resumes. Old sessions and runs are not restarted.",
  TERMS_SCOPE:
    "The service lets you build and test trading strategies with simulated funds. It does not place real trades or hold trading funds. You are responsible for your strategy settings. Examples and simulated results do not guarantee profits or future performance.",
  HISTORY_RETENTION: `We keep up to ${contract.resourcePolicy.retained_runs} completed runs per account for up to ${contract.resourcePolicy.history_retention_days} days. Deleting a bot hides it from your bot list but does not erase its stored settings or past runs. Account deletion removes saved bots and graphs.`,
  DELETION_RETENTION: `You can request account deletion in Account settings by confirming your password. Access is revoked and runs stop immediately. Account data is scheduled for removal within ${contract.dataLifecycle.deletionTargetHours} hours; maintenance failures may delay removal. Audit records may remain for ${contract.dataLifecycle.auditRetentionDays} days, and encrypted backups expire within ${contract.dataLifecycle.backupRetentionDays} days.`,
  LINK_LIFETIME: `Links expire after ${contract.accountManagement.tokenLifetimeMinutes} minutes and can be used once.`,
} as const;
