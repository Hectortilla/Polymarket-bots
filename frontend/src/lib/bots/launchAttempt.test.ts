import { beforeEach, describe, expect, it } from "vitest";
import { IDEMPOTENCY_KEY_HEADER, IDEMPOTENCY_RECOVERY_HEADER } from "$lib/api/http";
import { LaunchAttempt } from "./launchAttempt";

describe("pending run launch identity", () => {
  beforeEach(() => sessionStorage.clear());

  it("recovers the same logical launch after failure or reload", () => {
    const attempt = new LaunchAttempt("bot-a");
    const headers = attempt.requestHeaders();
    const key = headers[IDEMPOTENCY_KEY_HEADER];
    expect(headers[IDEMPOTENCY_RECOVERY_HEADER]).toBe(String(false));
    expect(attempt.requestHeaders()[IDEMPOTENCY_RECOVERY_HEADER]).toBe(String(true));
    expect(attempt.requestHeaders()[IDEMPOTENCY_KEY_HEADER]).toBe(key);
    expect(new LaunchAttempt("bot-a").requestHeaders()[IDEMPOTENCY_KEY_HEADER]).toBe(key);
    expect(new LaunchAttempt("bot-b").requestHeaders()[IDEMPOTENCY_KEY_HEADER]).not.toBe(key);
  });

  it("permits an explicit new run after confirmation", () => {
    const attempt = new LaunchAttempt("bot-a");
    const key = attempt.requestHeaders()[IDEMPOTENCY_KEY_HEADER];
    attempt.complete();
    expect(attempt.requestHeaders()[IDEMPOTENCY_KEY_HEADER]).not.toBe(key);
  });

  it("repairs malformed stored input at the storage boundary", () => {
    const attempt = new LaunchAttempt("bot");
    attempt.requestHeaders()[IDEMPOTENCY_KEY_HEADER];
    const storageKey = sessionStorage.key(0)!;
    sessionStorage.setItem(storageKey, "invalid old value");
    const repaired = attempt.requestHeaders()[IDEMPOTENCY_KEY_HEADER];
    expect(repaired).toMatch(/^[0-9a-f-]{36}$/);
    expect(sessionStorage.getItem(storageKey)).toBe(repaired);
  });
});
