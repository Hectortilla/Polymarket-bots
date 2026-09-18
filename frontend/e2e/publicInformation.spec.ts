import { ACCOUNT_COPY } from "../src/lib/auth/recovery/copy";
import { PUBLIC_COPY } from "../src/lib/public/copy";
import { test, expect } from "@playwright/test";
import {
  PUBLIC_INFORMATION_PATH,
  PUBLIC_INFORMATION_LABEL,
  PUBLIC_INFORMATION_NAV_LABEL,
} from "../src/lib/public/navigation";
import { SERVICE_IDENTITY, SUPPORT_PENDING } from "../src/lib/public/identity";
import { REGISTER_PATH, LOGIN_PATH } from "../src/lib/auth/navigation";
import { AUTH_COPY } from "../src/lib/auth/copy";
import { NAVIGATION_PATH } from "../src/lib/navigation";
import contract from "../src/lib/runtimeContract.fixture.json" with { type: "json" };
import { HTTP_STATUS } from "../src/lib/api/http";

test("anonymous information navigation never requests private resources and account links remain usable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (["fetch", "xhr"].includes(request.resourceType())) apiRequests.push(request.url());
  });
  await page.goto(PUBLIC_INFORMATION_PATH.WELCOME);
  await expect(page.getByRole("status")).toHaveText(SUPPORT_PENDING);
  for (const path of Object.values(PUBLIC_INFORMATION_PATH)) {
    const link = page
      .getByRole("navigation", { name: PUBLIC_INFORMATION_NAV_LABEL })
      .getByRole("link", { name: PUBLIC_INFORMATION_LABEL[path], exact: true });
    await link.hover();
    await link.click();
    await expect(page).toHaveURL((url) => url.pathname === path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(
      page.getByRole("banner").getByRole("link", { name: SERVICE_IDENTITY.name, exact: true }),
    ).toHaveAttribute("href", NAVIGATION_PATH.HOME);
    await expect(page.getByRole("banner").getByRole("link", { name: AUTH_COPY.SIGN_IN, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.goto("/%77elcome");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(apiRequests).toEqual([]);
  await page.getByRole("banner").getByRole("link", { name: AUTH_COPY.SIGN_IN, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === LOGIN_PATH);
  await expect(page.getByLabel(AUTH_COPY.EMAIL, { exact: true })).toBeVisible();
  await expect(
    page
      .getByRole("banner")
      .getByRole("link", { name: PUBLIC_INFORMATION_LABEL[PUBLIC_INFORMATION_PATH.HELP], exact: true }),
  ).toBeVisible();
  expect(apiRequests.some((url) => new URL(url).pathname === contract.apiPaths.currentUser)).toBe(true);
  await page.goto(NAVIGATION_PATH.HOME);
  await expect(page).toHaveURL((url) => url.pathname === LOGIN_PATH);
  await page.goto(PUBLIC_INFORMATION_PATH.SUPPORT);
  await page.getByRole("link", { name: PUBLIC_COPY.RECOVER }).click();
  await expect(page).toHaveURL((url) => url.pathname === contract.accountManagement.forgotPath);
  await expect(page.getByLabel(AUTH_COPY.EMAIL, { exact: true })).toBeVisible();
});

test("the shared header keeps account controls on public pages without private polling and supports sign out", async ({
  page,
}) => {
  await page.goto(REGISTER_PATH);
  const email = `public-reader-${Date.now()}@example.com`;
  await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(email);
  await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill("disposable public reader password 123");
  await page.getByRole("button", { name: AUTH_COPY.REGISTER, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === contract.accountManagement.accountPath);
  await page
    .getByRole("link", { name: PUBLIC_INFORMATION_LABEL[PUBLIC_INFORMATION_PATH.HELP], exact: true })
    .click();
  await expect(page).toHaveURL((url) => url.pathname === PUBLIC_INFORMATION_PATH.HELP);
  const privateRequests: string[] = [];
  page.on("request", (request) => {
    if (["fetch", "xhr"].includes(request.resourceType())) privateRequests.push(request.url());
  });
  const header = page.getByRole("banner");
  for (const path of Object.values(PUBLIC_INFORMATION_PATH)) {
    await page
      .getByRole("navigation", { name: PUBLIC_INFORMATION_NAV_LABEL })
      .getByRole("link", { name: PUBLIC_INFORMATION_LABEL[path], exact: true })
      .click();
    await expect(page).toHaveURL((url) => url.pathname === path);
    await expect(header.getByText(email, { exact: true })).toBeVisible();
    await expect(header.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
    await expect(header.getByRole("link", { name: ACCOUNT_COPY.SETTINGS, exact: true })).toBeVisible();
    await expect(header.getByRole("link", { name: AUTH_COPY.SIGN_IN, exact: true })).toHaveCount(0);
  }
  // Wait across the actual session interval while preserving the live client account.
  await page.waitForTimeout(contract.auth.sessionRecheckMs + 250);
  expect(privateRequests).toEqual([]);
  await header.getByRole("link", { name: ACCOUNT_COPY.SETTINGS, exact: true }).click();
  await expect(page.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
  await expect
    .poll(() => privateRequests.some((url) => new URL(url).pathname === contract.apiPaths.currentUser))
    .toBe(true);
  await expect(header.getByText(email, { exact: true })).toBeVisible();
  await header.getByRole("link", { name: SERVICE_IDENTITY.name, exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === NAVIGATION_PATH.HOME);
  await expect(page.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true })).toBeVisible();
  await header.getByRole("link", { name: PUBLIC_INFORMATION_LABEL[PUBLIC_INFORMATION_PATH.HELP], exact: true }).click();
  await page.route(
    `**${contract.apiPaths.logout}`,
    (route) => route.fulfill({ status: HTTP_STATUS.SERVICE_UNAVAILABLE, body: "{}" }),
    { times: 1 },
  );
  await header.getByRole("button", { name: AUTH_COPY.SIGN_OUT, exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(AUTH_COPY.SIGN_OUT_ERROR);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Retry sign out", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(header.getByRole("link", { name: AUTH_COPY.SIGN_IN, exact: true })).toBeVisible();
  await expect(page).toHaveURL((url) => url.pathname === PUBLIC_INFORMATION_PATH.HELP);
});

test("public claims and links reflect paper-only operation and the generated data policy", async ({ page }) => {
  await page.goto(PUBLIC_INFORMATION_PATH.WELCOME);
  await expect(page.getByText(PUBLIC_COPY.SIMULATION, { exact: true })).toBeVisible();
  await expect(page.getByText(PUBLIC_COPY.ACCOUNT_LIMITS, { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: AUTH_COPY.REGISTER, exact: true })).toHaveAttribute(
    "href",
    REGISTER_PATH,
  );
  await page.goto(PUBLIC_INFORMATION_PATH.HELP);
  await expect(page.getByText(PUBLIC_COPY.SAVE_BEFORE_RUN, { exact: true })).toBeVisible();
  await expect(page.getByText(PUBLIC_COPY.LINK_LIFETIME, { exact: false })).toBeVisible();
  await expect(page.getByRole("link", { name: ACCOUNT_COPY.RESET_TITLE, exact: true })).toHaveAttribute(
    "href",
    contract.accountManagement.forgotPath,
  );
  await page.goto(PUBLIC_INFORMATION_PATH.PRIVACY);
  await expect(page.getByText(PUBLIC_COPY.ACCOUNT_DATA, { exact: true })).toBeVisible();
  await expect(page.getByText(PUBLIC_COPY.HISTORY_RETENTION, { exact: true })).toBeVisible();
  await expect(page.getByText(PUBLIC_COPY.DELETION_RETENTION, { exact: true })).toBeVisible();
  await expect(page.getByText(PUBLIC_COPY.RESTORE_QUARANTINE, { exact: true })).toBeVisible();
  await page.goto(PUBLIC_INFORMATION_PATH.TERMS);
  await expect(page.getByText(PUBLIC_COPY.TERMS_SCOPE, { exact: true })).toBeVisible();
  await page.goto(PUBLIC_INFORMATION_PATH.SUPPORT);
  await expect(page.getByRole("status")).toHaveText(SUPPORT_PENDING);
  await expect(page.getByText(PUBLIC_COPY.RESPONSIBLE_OPERATOR, { exact: false })).toContainText(
    SERVICE_IDENTITY.operator,
  );
  await expect(page.getByRole("link", { name: PUBLIC_COPY.RECOVER })).toHaveAttribute(
    "href",
    contract.accountManagement.forgotPath,
  );
});
