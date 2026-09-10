import accountContract from "./accountContract.fixture.json" with { type: "json" };
import { test, expect } from "@playwright/test";
import contract from "../src/lib/runtimeContract.fixture.json" with { type: "json" };
import { ACCOUNT_COPY } from "../src/lib/auth/recovery/copy";
import { AUTH_COPY } from "../src/lib/auth/copy";
import { LOGIN_PATH, REGISTER_PATH } from "../src/lib/auth/navigation";
import { receivedLink } from "./accountHelpers";

const PASSWORD = "browser recovery original password";
const NEW_PASSWORD = "browser recovery replaced password";
const EMAIL = "browser-recovery@example.com";

test.beforeEach(async ({ request }) => {
  await request.post(accountContract.clearLimitsPath);
});

test("mail reset removes URL secrets, rejects replay, and supports password/session changes", async ({
  page,
  browser,
}) => {
  await page.goto(REGISTER_PATH);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(EMAIL);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: AUTH_COPY.REGISTER, exact: true }).click();
  await expect(page).toHaveURL(contract.accountManagement.accountPath);
  await expect(page.getByText(ACCOUNT_COPY.VERIFICATION_REQUIRED)).toBeVisible();
  await page.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true }).click();
  await page.goto(contract.accountManagement.forgotPath);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(EMAIL);
  await page.getByRole("button", { name: ACCOUNT_COPY.SEND_RESET, exact: true }).click();
  await expect(page.getByRole("status")).toContainText(ACCOUNT_COPY.SENT);
  const link = await receivedLink(page, EMAIL);
  const token = new URL(link).hash.slice(1);
  await page.goto(link);
  await expect(page).toHaveURL((url) => !url.hash && !url.search);
  expect(
    await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } })),
  ).not.toContain(token);
  await page.getByLabel(ACCOUNT_COPY.NEW_PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByLabel(ACCOUNT_COPY.CONFIRM_PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByRole("button", { name: ACCOUNT_COPY.COMPLETE_RESET, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === LOGIN_PATH);
  await expect(page.getByRole("status")).toContainText(ACCOUNT_COPY.DONE);
  await page.goto(link);
  await page.getByLabel(ACCOUNT_COPY.NEW_PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByLabel(ACCOUNT_COPY.CONFIRM_PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByRole("button", { name: ACCOUNT_COPY.COMPLETE_RESET, exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(ACCOUNT_COPY.INVALID_LINK);
  await page.goto(LOGIN_PATH);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(EMAIL);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByRole("button", { name: AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
  const peer = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const peerLogin = await peer.request.post(contract.apiPaths.login, {
    headers: { Origin: new URL(page.url()).origin },
    data: { email: EMAIL, password: NEW_PASSWORD },
  });
  expect(peerLogin.ok()).toBe(true);
  await page.goto(contract.accountManagement.accountPath);
  await page.getByLabel(ACCOUNT_COPY.CURRENT_PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByRole("button", { name: ACCOUNT_COPY.REVOKE_OTHER, exact: true }).click();
  await expect(page.getByRole("status")).toContainText(ACCOUNT_COPY.OTHERS_DONE);
  expect((await peer.request.get(contract.apiPaths.currentUser)).status()).toBe(contract.httpStatus.UNAUTHORIZED);
  await page.getByLabel(ACCOUNT_COPY.CURRENT_PASSWORD, { exact: true }).fill(NEW_PASSWORD);
  await page.getByLabel(ACCOUNT_COPY.NEW_PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByLabel(ACCOUNT_COPY.CONFIRM_PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: ACCOUNT_COPY.CHANGE_PASSWORD, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === LOGIN_PATH);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(EMAIL);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
  await page.goto(contract.accountManagement.accountPath);
  await page.getByLabel(ACCOUNT_COPY.CURRENT_PASSWORD, { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: ACCOUNT_COPY.REVOKE_ALL, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === LOGIN_PATH);
  await expect(page.getByRole("status")).toContainText(ACCOUNT_COPY.DONE);
  expect((await page.request.get(contract.apiPaths.currentUser)).status()).toBe(contract.httpStatus.UNAUTHORIZED);
  await peer.close();
});

test("missing links and delivery failures have actionable browser states", async ({ page }) => {
  await page.goto(contract.accountManagement.resetPath);
  await expect(page.getByRole("alert")).toContainText(ACCOUNT_COPY.INVALID_LINK);
  await page.goto(contract.accountManagement.forgotPath);
  await page.route(`**${contract.apiPaths.requestPasswordReset}`, (route) =>
    route.fulfill({ status: contract.httpStatus.SERVICE_UNAVAILABLE, json: { detail: "unavailable" } }),
  );
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(EMAIL);
  await page.getByRole("button", { name: ACCOUNT_COPY.SEND_RESET, exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(ACCOUNT_COPY.DELIVERY_FAILED);
  await expect(page.getByRole("status")).toHaveCount(0);
});
