import { ACCOUNT_COPY } from "$lib/auth/recovery/copy";
import contract from "$lib/runtimeContract.fixture.json" with { type: "json" };
import { minutesFromSeconds } from "$lib/time";

export const PUBLIC_COPY = {
  SUPPORT: "Support and feedback",
  DATA_POLICY: "data policy",
  RECOVER: "Reset a forgotten password",
  RESET: "Reset your password",
  SIMULATION:
    "Paper orders do not place real orders or move funds. Simulated fills, fees, latency and balances do not establish real liquidity, queue priority, execution quality or future performance. This beta offers neither live execution nor a strategy marketplace.",
  SAVE_BEFORE_RUN:
    "Review the settings and save your private bot. Saving does not start execution. Press Run on the saved bot page.",
  ACCOUNT_DATA:
    "We store your email, password hash, session and recovery-token digests, verification state and account timestamps to authenticate you and recover access. A session cookie keeps you signed in. We store your private bot settings, strategy graphs and revisions, selected public market or wallet identifiers, and run history including orders, fills, progress and simulated balances. Other accounts cannot access those private resources.",
  RESTORE_QUARANTINE:
    "A restored backup stays quarantined: old sessions are revoked, execution is paused and deletion requests must be reconciled before access can reopen. Operators retain a minimal deletion receipt for that reconciliation during the audit period.",
  TERMS_SCOPE:
    "The service builds and runs private strategies with simulated execution. It does not place real trades, hold trading funds or guarantee profits, real-world fills or future performance. You choose your strategy and settings; examples explain functionality and are not promises of returns.",
  SUPPORT_PLACEHOLDER:
    "The public support mailbox is a placeholder for now. The operator must publish a monitored address and test delivery before inviting public accounts. No message form submits feedback in this preview.",
  ACCOUNT_LIMITS: `Each account can have ${contract.resourcePolicy.active_runs} active run and ${contract.resourcePolicy.queued_runs} queued runs, with up to ${contract.resourcePolicy.saved_bots} saved bots. Each run supports ${contract.resourcePolicy.tracked_markets_per_run} tracked markets and ${contract.resourcePolicy.followed_wallets_per_run} followed wallets, and stops after ${minutesFromSeconds(contract.resourcePolicy.run_duration_seconds)} minutes.`,
  HISTORY_RETENTION: `Terminal run history is limited to ${contract.resourcePolicy.retained_runs} runs per account for at most ${contract.resourcePolicy.history_retention_days} days. Deleted bot configurations disappear from your workspace, but their data stays in the system and past runs remain under these history limits. Saved bot data and graphs are erased through account deletion.`,
  DELETION_RETENTION: `${ACCOUNT_COPY.SETTINGS} accept a password-confirmed deletion request. Access is revoked and execution is quiesced immediately; eligible account records are removed within ${contract.dataLifecycle.deletionTargetHours} hours when maintenance is healthy. Minimal operator audit records can remain for ${contract.dataLifecycle.auditRetentionDays} days. Encrypted backups age out after ${contract.dataLifecycle.backupRetentionDays} days, so deletion does not immediately rewrite existing backups.`,
  LINK_LIFETIME: `Links expire after ${contract.accountManagement.tokenLifetimeMinutes} minutes and can be used once.`,
  RESPONSIBLE_OPERATOR: "Responsible operator:",
} as const;
