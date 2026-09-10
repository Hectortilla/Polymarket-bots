import { IDEMPOTENCY_KEY_HEADER, IDEMPOTENCY_RECOVERY_HEADER } from "$lib/api/http";

/** A pending launch survives response loss and reload in this browser tab. */
const PENDING_LAUNCH_STORAGE_KEY_PREFIX = "polybot.pending-launch:";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export class LaunchAttempt {
  constructor(
    private readonly botId: string,
    private readonly storage: Storage = sessionStorage,
  ) {}

  requestHeaders(): Record<string, string> {
    const storageKey = PENDING_LAUNCH_STORAGE_KEY_PREFIX + this.botId;
    const existing = this.storage.getItem(storageKey);
    if (existing && UUID_PATTERN.test(existing))
      return { [IDEMPOTENCY_KEY_HEADER]: existing.toLowerCase(), [IDEMPOTENCY_RECOVERY_HEADER]: String(true) };
    const idempotencyKey = crypto.randomUUID();
    // Persist before sending. If browser storage is unavailable, fail before
    // launch so reload cannot silently turn an uncertain result into a new run.
    this.storage.setItem(storageKey, idempotencyKey);
    return { [IDEMPOTENCY_KEY_HEADER]: idempotencyKey, [IDEMPOTENCY_RECOVERY_HEADER]: String(false) };
  }

  complete(): void {
    this.storage.removeItem(PENDING_LAUNCH_STORAGE_KEY_PREFIX + this.botId);
  }
}
