import { test, expect, type Page } from '@playwright/test';
import contract from '../src/lib/runtimeContract.fixture.json' with { type: 'json' };

import { AUTH_COPY } from '../src/lib/auth/copy';
import { LOGIN_PATH, REGISTER_PATH, RETURN_TO_QUERY_PARAM } from '../src/lib/auth/navigation';
import { NAVIGATION_PATH } from '../src/lib/navigation';
import { BOT_BUILDER_COPY } from '../src/lib/bots/copy';
import { BOT_DETAIL_COPY } from '../src/routes/bots/[botId]/copy';
import { RUN_STATUS, RUN_STATUS_PRESENTATION } from '../src/lib/runs/status';
import { CONTENT_TYPE_HEADER, HTTP_STATUS, JSON_CONTENT_TYPE } from '../src/lib/api/http';

const STREAM_COUNTERS = { opened: 'test-stream-opened', closed: 'test-stream-closed' };

const PASSWORD = 'browser test password 123';
const FIRST_EMAIL = 'browser-first@example.com';
const SECOND_EMAIL = 'browser-second@example.com';

async function authenticate(page: Page, email: string, registration = false) {
  await page.goto(registration ? REGISTER_PATH : LOGIN_PATH);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(email);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: registration ? AUTH_COPY.REGISTER : AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page.getByRole('button', { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
  await expect(page).toHaveURL(NAVIGATION_PATH.HOME);
}

async function configureBot(page: Page, name: string) {
  await page.goto(NAVIGATION_PATH.NEW_BOT);
  await page.getByLabel('Name', { exact: true }).fill(name);
  await page.getByPlaceholder('Search markets by name or topic…').fill('browser');
  await page.getByRole('option').filter({ hasText: 'Will browser-market happen?' }).click();
}

test('two accounts keep editor, copies, runs and history private across reload and switching', async ({ page, browser }) => {
  const privateRequests: string[] = [];
  page.on('request', request => { if ([contract.apiPaths.bots, contract.apiPaths.runs].some(path => request.url().endsWith(path))) privateRequests.push(request.url()); });
  await page.goto(NAVIGATION_PATH.HOME);
  await expect(page).toHaveURL(url => url.pathname === LOGIN_PATH && url.searchParams.has(RETURN_TO_QUERY_PARAM));
  expect(privateRequests).toEqual([]);
  await authenticate(page, FIRST_EMAIL, true);
  await page.reload();
  await expect(page.getByText(FIRST_EMAIL, { exact: true })).toBeVisible();
  await configureBot(page, 'First private bot');
  await page.getByRole('button', { name: BOT_BUILDER_COPY.CREATE, exact: true }).click();
  await expect(page).toHaveURL(/\/bots\/[a-f0-9-]+$/);
  const botUrl = page.url();
  await page.getByLabel('Name', { exact: true }).fill('First edited bot');
  await page.getByRole('button', { name: BOT_DETAIL_COPY.SAVE_CHANGES, exact: true }).click();
  await expect(page.getByRole('button', { name: BOT_DETAIL_COPY.RUN, exact: true })).toBeEnabled();
  await page.getByRole('button', { name: BOT_DETAIL_COPY.RUN, exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/[a-f0-9-]+$/);
  const runUrl = page.url();
  await page.getByRole('button', { name: RUN_STATUS_PRESENTATION[RUN_STATUS.QUEUED].stopLabel!, exact: true }).click();
  await expect(page.getByText(RUN_STATUS_PRESENTATION[RUN_STATUS.STOPPED].label, { exact: true }).first()).toBeVisible();
  await configureBot(page, 'First copied bot');
  await page.getByLabel('Starting point').selectOption({ label: 'First edited bot' });
  await page.getByRole('button', { name: BOT_BUILDER_COPY.COPY_GRAPH, exact: true }).click();
  await page.getByRole('button', { name: BOT_BUILDER_COPY.CREATE, exact: true }).click();
  await expect(page).toHaveURL(/\/bots\/[a-f0-9-]+$/);

  const secondContext = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const second = await secondContext.newPage();
  await authenticate(second, SECOND_EMAIL, true);
  await expect(second.getByText('First edited bot', { exact: true })).toHaveCount(0);
  await second.goto(botUrl);
  await expect(second.getByText(BOT_DETAIL_COPY.NOT_FOUND, { exact: true })).toBeVisible();
  await second.goto(runUrl);
  await expect(second.getByRole('alert')).toBeVisible();
  await second.goto(NAVIGATION_PATH.NEW_BOT);
  await expect(second.getByLabel('Starting point')).not.toContainText('First edited bot');
  const runId = runUrl.split('/').pop()!;
  const denied = await secondContext.request.get(contract.apiPaths.runEvents.replace('{run_id}', runId));
  expect(denied.status()).toBe(HTTP_STATUS.NOT_FOUND);
  await secondContext.close();

  await page.getByRole('button', { name: AUTH_COPY.SIGN_OUT, exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === LOGIN_PATH);
  await authenticate(page, SECOND_EMAIL);
  await expect(page.getByText('First edited bot', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: AUTH_COPY.SIGN_OUT, exact: true }).click();
  await authenticate(page, FIRST_EMAIL);
  await page.goto(runUrl);
  await expect(page.getByText(RUN_STATUS_PRESENTATION[RUN_STATUS.STOPPED].label, { exact: true }).first()).toBeVisible();
  // Revoke outside the current page: the shell's bounded restoration detects expiry.
  await page.context().request.post(contract.apiPaths.logout, { headers: { Origin: new URL(page.url()).origin, [CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE } });
  await expect(page).toHaveURL(url => url.pathname === LOGIN_PATH, { timeout: contract.auth.sessionRecheckMs + 5000 });
  await expect(page.getByText('First edited bot', { exact: true })).toHaveCount(0);
  await page.goto(`${LOGIN_PATH}?${RETURN_TO_QUERY_PARAM}=https://foreign.example/`);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(FIRST_EMAIL);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill('wrong password long enough');
  await page.getByRole('button', { name: AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(AUTH_COPY.LOGIN_ERROR);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page).toHaveURL(NAVIGATION_PATH.HOME);
});




test('active streams close on logout, external revocation, and cross-tab account switching', async ({ page, browser }) => {
  const firstActiveEmail = 'active-first@example.com';
  const secondActiveEmail = 'active-second@example.com';
  const secondContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const secondPage = await secondContext.newPage();
  await authenticate(secondPage, secondActiveEmail, true);
  await secondContext.close();

  await installStreamLifecycleCounters(page);

  await authenticate(page, firstActiveEmail, true);
  for (const transition of ['logout', 'revocation', 'switch'] as const) {
    if (transition !== 'logout') await authenticate(page, firstActiveEmail);
    const opened = await streamCount(page, STREAM_COUNTERS.opened);
    const closed = await streamCount(page, STREAM_COUNTERS.closed);
    await configureBot(page, `Active ${transition} bot`);
    await page.getByRole('button', { name: BOT_BUILDER_COPY.CREATE, exact: true }).click();
    await expect(page).toHaveURL(/\/bots\/[a-f0-9-]+$/);
    await page.getByRole('button', { name: BOT_DETAIL_COPY.RUN, exact: true }).click();
    await expect(page).toHaveURL(/\/runs\/[a-f0-9-]+$/);
    await expect.poll(() => streamCount(page, STREAM_COUNTERS.opened)).toBeGreaterThan(opened);

    if (transition === 'logout') {
      await page.getByRole('button', { name: AUTH_COPY.SIGN_OUT, exact: true }).click();
      await expect(page).toHaveURL(url => url.pathname === LOGIN_PATH);
    } else if (transition === 'revocation') {
      await page.context().request.post(contract.apiPaths.logout, {
        headers: { Origin: new URL(page.url()).origin, [CONTENT_TYPE_HEADER]: JSON_CONTENT_TYPE },
      });
      await expect(page).toHaveURL(url => url.pathname === LOGIN_PATH, { timeout: contract.auth.sessionRecheckMs + 5000 });
    } else {
      const peer = await page.context().newPage();
      await authenticate(peer, secondActiveEmail);
      await expect(page.getByText(secondActiveEmail, { exact: true })).toBeVisible();
      await expect(page.getByText(`Active ${transition} bot`, { exact: true })).toHaveCount(0);
      await peer.close();
    }
    await expect.poll(() => streamCount(page, STREAM_COUNTERS.closed)).toBeGreaterThan(closed);
  }
});

async function installStreamLifecycleCounters(page: Page): Promise<void> {
  await page.addInitScript((keys) => {
    const NativeEventSource = window.EventSource;
    const increment = (key: string) => sessionStorage.setItem(key, String(Number(sessionStorage.getItem(key) ?? 0) + 1));
    window.EventSource = class extends NativeEventSource {
      private closedByApplication = false;
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options);
        this.addEventListener('open', () => increment(keys.opened));
      }
      close() {
        if (!this.closedByApplication) increment(keys.closed);
        this.closedByApplication = true;
        super.close();
      }
    };
  }, STREAM_COUNTERS);
}

function streamCount(page: Page, key: string): Promise<number> {
  return page.evaluate(storageKey => Number(sessionStorage.getItem(storageKey) ?? 0), key);
}
