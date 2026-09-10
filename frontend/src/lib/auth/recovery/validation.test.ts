import { ACCOUNT_COPY } from './copy';
import { AUTH_COPY } from '../copy';
import { accountStatusMessage } from './presentation';
import { accountActionError } from './result';
import { describe, expect, it } from 'vitest';
import { CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE, HTTP_STATUS } from '$lib/api/http';
import { validateOperationResponse } from '$lib/api/responseValidation/operations';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { passwordsMatch } from './validation';

const paths = runtimeContract.apiPaths;
const actionPaths = [paths.requestPasswordReset, paths.completePasswordReset,
  paths.requestEmailVerification, paths.completeEmailVerification,
  paths.changePassword, paths.revokeSessions, paths.requestAccountDeletion];

function validate(url: string, body: unknown) {
  return validateOperationResponse(new Response(JSON.stringify(body), {
    headers: { [CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE },
  }), new Request('https://control-plane.test'), { url });
}

describe('account operation responses', () => {
  it.each(actionPaths)('requires exact acceptance for %s', async (path) => {
    await expect(validate(path, { accepted: true })).resolves.toBeInstanceOf(Response);
    for (const body of [null, {}, { accepted: false }, { accepted: 'true' },
      { accepted: true, token: 'unexpected' }]) {
      await expect(validate(path, body)).rejects.toThrow('operation validation');
    }
  });

  it('requires both account status flags without extra fields', async () => {
    for (const email_verified of [true, false]) {
      for (const verification_required of [true, false]) {
        await expect(validate(paths.accountStatus, { email_verified, verification_required }))
          .resolves.toBeInstanceOf(Response);
      }
    }
    for (const body of [null, {}, { email_verified: false },
      { email_verified: false, verification_required: 'false' },
      { email_verified: false, verification_required: true, password: 'unexpected' }]) {
      await expect(validate(paths.accountStatus, body)).rejects.toThrow('operation validation');
    }
  });

  it('requires an exact password confirmation', () => {
    expect(passwordsMatch('exact password', 'exact password')).toBe(true);
    expect(passwordsMatch('exact password', 'Exact password')).toBe(false);
    expect(passwordsMatch('exact password', 'exact password ')).toBe(false);
  });
});

describe('account status and action copy', () => {
  it.each([true, false])('shows verified status regardless of requirement %s', (verification_required) => {
    expect(accountStatusMessage({ email_verified: true, verification_required })).toBe(ACCOUNT_COPY.VERIFIED);
  });
  it('distinguishes required verification from retained legacy access', () => {
    expect(accountStatusMessage({ email_verified: false, verification_required: true })).toBe(ACCOUNT_COPY.VERIFICATION_REQUIRED);
    expect(accountStatusMessage({ email_verified: false, verification_required: false })).toBe(ACCOUNT_COPY.LEGACY_ACCOUNT);
  });
  it.each([undefined, HTTP_STATUS.INTERNAL_SERVER_ERROR, HTTP_STATUS.SERVICE_UNAVAILABLE])('shows service failure for %s', (status) => {
    expect(accountActionError(status)).toBe(AUTH_COPY.SERVICE_ERROR);
  });
  it('distinguishes throttling and reauthentication or link rejection', () => {
    expect(accountActionError(HTTP_STATUS.TOO_MANY_REQUESTS)).toBe(AUTH_COPY.RATE_LIMIT_ERROR);
    expect(accountActionError(HTTP_STATUS.FORBIDDEN)).toBe(ACCOUNT_COPY.REAUTH_FAILED);
    expect(accountActionError(HTTP_STATUS.BAD_REQUEST, ACCOUNT_COPY.INVALID_LINK)).toBe(ACCOUNT_COPY.INVALID_LINK);
  });
});
