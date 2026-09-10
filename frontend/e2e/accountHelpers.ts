import accountContract from "./accountContract.fixture.json" with { type: "json" };
import { expect, type Page } from "@playwright/test";
import contract from "../src/lib/runtimeContract.fixture.json" with { type: "json" };
import { ACCOUNT_COPY } from "../src/lib/auth/recovery/copy";
import { AUTH_COPY } from "../src/lib/auth/copy";
import { LOGIN_PATH } from "../src/lib/auth/navigation";

export const MAILBOX_PATH = accountContract.mailboxPath;

export async function receivedLink(page: Page, email: string): Promise<string> {
  const result = await page.request.get(MAILBOX_PATH, { params: { [accountContract.mailboxEmailParameter]: email } });
  expect(result.ok()).toBe(true);
  return (await result.json())[accountContract.mailboxLinkField];
}

export async function verifyNewAccount(page: Page, email: string, password: string): Promise<void> {
  await expect(page).toHaveURL(contract.accountManagement.accountPath);
  await page.getByRole("button", { name: ACCOUNT_COPY.SEND_VERIFICATION, exact: true }).click();
  await expect(page.getByRole("status")).toContainText(ACCOUNT_COPY.SENT);
  await page.goto(await receivedLink(page, email));
  await page.getByLabel(ACCOUNT_COPY.NEW_PASSWORD, { exact: true }).fill(password);
  await page.getByLabel(ACCOUNT_COPY.CONFIRM_PASSWORD, { exact: true }).fill(password);
  await page.getByRole("button", { name: ACCOUNT_COPY.COMPLETE_VERIFICATION, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === LOGIN_PATH);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(email);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(password);
  await page.getByRole("button", { name: AUTH_COPY.SIGN_IN, exact: true }).click();
}
