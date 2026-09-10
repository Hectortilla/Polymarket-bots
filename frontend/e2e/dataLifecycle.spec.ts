import { test, expect } from '@playwright/test';
import accountContract from './accountContract.fixture.json' with { type: 'json' };
import contract from '../src/lib/runtimeContract.fixture.json' with { type: 'json' };
import { AUTH_COPY } from '../src/lib/auth/copy';
import { LOGIN_PATH, REGISTER_PATH } from '../src/lib/auth/navigation';
import { ACCOUNT_COPY } from '../src/lib/auth/recovery/copy';
import { LIFECYCLE_COPY } from '../src/lib/lifecycle/copy';

const PASSWORD = 'browser deletion password';

test('account deletion requires confirmation, revokes access and explains expiry', async ({ page }) => {
  await page.request.post(accountContract.clearLimitsPath);
  await page.goto(REGISTER_PATH);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill('browser-deletion@example.com');
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: AUTH_COPY.REGISTER, exact: true }).click();
  await expect(page).toHaveURL(contract.accountManagement.accountPath);
  await expect(page.getByText(LIFECYCLE_COPY.HISTORY)).toBeVisible();
  await expect(page.getByRole('button', { name: LIFECYCLE_COPY.DELETE, exact: true })).toBeDisabled();
  await page.getByLabel(LIFECYCLE_COPY.PASSWORD, { exact: true }).fill('incorrect browser password');
  await page.getByLabel(LIFECYCLE_COPY.CONFIRM, { exact: true }).check();
  await page.getByRole('button', { name: LIFECYCLE_COPY.DELETE, exact: true }).click();
  await expect(page.getByRole('region', { name: LIFECYCLE_COPY.DELETE_HEADING }).getByRole('alert')).toContainText(ACCOUNT_COPY.REAUTH_FAILED);
  expect((await page.request.get(contract.apiPaths.currentUser)).ok()).toBe(true);
  await page.getByLabel(LIFECYCLE_COPY.PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: LIFECYCLE_COPY.DELETE, exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === LOGIN_PATH);
  await expect(page.getByRole('status')).toContainText(LIFECYCLE_COPY.REQUESTED);
  expect((await page.request.get(contract.apiPaths.currentUser)).status()).toBe(contract.httpStatus.UNAUTHORIZED);
});
