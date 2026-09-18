import { test, expect } from "@playwright/test";
import accountContract from "./accountContract.fixture.json" with { type: "json" };
import contract from "../src/lib/runtimeContract.fixture.json" with { type: "json" };
import { AUTH_COPY } from "../src/lib/auth/copy";

const admin = accountContract.admin;
const adminPath = contract.admin.path;

test("admin login return, account inspection, read-only views and logout", async ({ page }) => {
  await page.request.post(accountContract.clearLimitsPath);
  await page.goto(adminPath);
  await expect(page).toHaveURL(/\/login\?returnTo=/);
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(admin.email);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(admin.password);
  await page.getByRole("button", { name: AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page).toHaveURL(adminPath + "/");
  await expect(page.getByText("Read-only administration")).toBeVisible();
  const scripts = await page
    .locator("script[src]")
    .evaluateAll((nodes) => nodes.map((node) => (node as HTMLScriptElement).src));
  for (const script of scripts) expect((await page.request.get(script)).ok()).toBe(true);
  await page.goto(`${adminPath}/${admin.userView}/list`);
  await expect(page.getByRole("table")).toContainText(admin.email);
  await page.getByRole("link", { name: "View", exact: true }).first().click();
  await expect(page.getByRole("link", { name: "User configurations" })).toBeVisible();
  await page.getByRole("link", { name: "User configurations" }).click();
  await expect(page.getByLabel("Owner user ID")).not.toHaveValue("");
  await expect(page.getByRole("link", { name: /New Configuration/ })).toHaveCount(0);
  await page.goto(`${adminPath}/${admin.runView}/list`);
  await expect(page.getByLabel("Status", { exact: true })).toBeVisible();
  expect((await page.request.get(`${adminPath}/${admin.userView}/export/csv`)).status()).toBe(404);
  await page.getByRole("link", { name: "Return to application" }).click();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page.getByText("Read-only administration")).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  const response = await page.request.get(`${adminPath}/${admin.userView}/list`, { maxRedirects: 0 });
  expect(response.status()).toBe(302);
  expect(response.headers()["cache-control"]).toBe("no-store");
});

test("ordinary accounts cannot open admin pages or see admin navigation", async ({ page }) => {
  await page.request.post(accountContract.clearLimitsPath);
  await page.goto("/register");
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(`admin-denied-${Date.now()}@example.com`);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill("ordinary browser password 123");
  await page.getByRole("button", { name: AUTH_COPY.REGISTER, exact: true }).click();
  await expect(page.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  const response = await page.goto(adminPath + "/");
  expect(response?.status()).toBe(403);
  await expect(page.getByText("administrator access required")).toBeVisible();
});
