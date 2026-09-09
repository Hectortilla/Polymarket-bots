import { beforeEach, describe, expect, it } from 'vitest';
import { LaunchAttempt } from './launchAttempt';

describe('pending run launch identity', () => {
  beforeEach(() => sessionStorage.clear());

  it('recovers the same logical launch after failure or reload', () => {
    const attempt = new LaunchAttempt('bot-a');
    const key = attempt.idempotencyKey();
    expect(attempt.idempotencyKey()).toBe(key);
    expect(new LaunchAttempt('bot-a').idempotencyKey()).toBe(key);
    expect(new LaunchAttempt('bot-b').idempotencyKey()).not.toBe(key);
  });

  it('permits an explicit new run after confirmation', () => {
    const attempt = new LaunchAttempt('bot-a');
    const key = attempt.idempotencyKey();
    attempt.complete();
    expect(attempt.idempotencyKey()).not.toBe(key);
  });

  it('repairs malformed stored input at the storage boundary', () => {
    const attempt = new LaunchAttempt('bot');
    attempt.idempotencyKey();
    const storageKey = sessionStorage.key(0)!;
    sessionStorage.setItem(storageKey, 'invalid old value');
    const repaired = attempt.idempotencyKey();
    expect(repaired).toMatch(/^[0-9a-f-]{36}$/);
    expect(sessionStorage.getItem(storageKey)).toBe(repaired);
  });
});
