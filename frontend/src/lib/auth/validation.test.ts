import { describe, expect, it } from 'vitest';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { CONTENT_TYPE_HEADER, JSON_CONTENT_TYPE } from '$lib/api/http';
import { validateOperationResponse } from '$lib/api/responseValidation/operations';

const user = { id: '11111111-1111-4111-8111-111111111111', email: 'first@example.com' };

describe('auth operation response validation', () => {
  it.each([
    runtimeContract.apiPaths.currentUser, runtimeContract.apiPaths.login, runtimeContract.apiPaths.register,
  ])('requires the current-user shape for %s', async (url) => {
    await expect(validate(url, user)).resolves.toBeInstanceOf(Response);
    for (const body of [{ email: user.email }, { ...user, id: 'invalid' }, { ...user, secret: 'hidden' }]) {
      await expect(validate(url, body)).rejects.toThrow('operation validation');
    }
  });

  it('requires a literal logout success with no extra fields', async () => {
    const url = runtimeContract.apiPaths.logout;
    await expect(validate(url, { logged_out: true })).resolves.toBeInstanceOf(Response);
    for (const body of [{}, { logged_out: false }, { logged_out: true, secret: 'hidden' }]) {
      await expect(validate(url, body)).rejects.toThrow('operation validation');
    }
  });
});

function validate(url: string, body: unknown): Promise<Response> {
  return validateOperationResponse(
    new Response(JSON.stringify(body), { headers: { [CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE } }),
    new Request('http://localhost' + url), { url },
  );
}
