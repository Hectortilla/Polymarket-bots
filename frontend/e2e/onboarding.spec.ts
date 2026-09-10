import { test, expect, type Page } from "@playwright/test";
import fixture from "./onboardingContract.fixture.json" with { type: "json" };
import browserContract from "./accountContract.fixture.json" with { type: "json" };
import contract from "../src/lib/runtimeContract.fixture.json" with { type: "json" };
import { verifyNewAccount } from "./accountHelpers";
import { AUTH_COPY } from "../src/lib/auth/copy";
import { REGISTER_PATH } from "../src/lib/auth/navigation";
import { NAVIGATION_PATH } from "../src/lib/navigation";
import { ONBOARDING_COPY } from "../src/lib/onboarding/copy";
import { RUN_GUIDE_COPY } from "../src/lib/runs/runGuide";
import { BOT_DETAIL_COPY } from "../src/routes/bots/[botId]/copy";
import { MARKET_SELECTOR_COPY } from "../src/lib/catalog/copy";
import { HTTP_STATUS } from "../src/lib/api/http";
import { RUN_STATUS, RUN_STATUS_PRESENTATION } from "../src/lib/runs/status";

const RUN_READY_TIMEOUT_MS = 20_000;

const expectations = {
  action: { guidance: RUN_GUIDE_COPY.ACTIONS, recoverSearch: true },
  waiting: { guidance: RUN_GUIDE_COPY.WAITING, recoverSearch: false },
} satisfies Record<keyof typeof fixture.cases, { guidance: string; recoverSearch: boolean }>;

for (const scenario of Object.keys(expectations) as (keyof typeof expectations)[]) {
  const { marketSlug, expectedFillCount } = fixture.cases[scenario];
  const expected = expectations[scenario];
  test(`guided ${scenario} paper run saves first, explains results and stops`, async ({ page, request }) => {
    await request.post(browserContract.clearLimitsPath);
    await page.setViewportSize({ width: 390, height: 844 });
    const password = "onboarding browser password 123";
    const email = `onboarding-${scenario}@example.com`;
    await page.goto(REGISTER_PATH);
    await page.getByLabel(AUTH_COPY.EMAIL, { exact: true }).fill(email);
    await page.getByLabel(AUTH_COPY.PASSWORD, { exact: true }).fill(password);
    await page.getByRole("button", { name: AUTH_COPY.REGISTER, exact: true }).click();
    await verifyNewAccount(page, email, password);
    await expect(page).toHaveURL(NAVIGATION_PATH.HOME);
    await page.getByRole("link", { name: ONBOARDING_COPY.START, exact: true }).click();
    await expect(page.getByRole("radio").first()).toBeChecked();
    const next = page.getByRole("button", { name: ONBOARDING_COPY.CONTINUE, exact: true });
    await next.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: ONBOARDING_COPY.SETTINGS, exact: true })).toBeFocused();
    await page.getByLabel("Name", { exact: true }).fill(`Guided ${scenario}`);
    if (expected.recoverSearch) {
      await page.route(
        `**${contract.apiPaths.marketSearch}*`,
        (route) => route.fulfill({ status: HTTP_STATUS.SERVICE_UNAVAILABLE, body: "{}" }),
        { times: 1 },
      );
      await page.getByRole("combobox").fill(marketSlug);
      await expect(page.getByText(MARKET_SELECTOR_COPY.SEARCH_ERROR, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: MARKET_SELECTOR_COPY.RETRY_SEARCH, exact: true }).click();
      await expect(page.getByLabel("Name", { exact: true })).toHaveValue(`Guided ${scenario}`);
    } else {
      await page.getByRole("combobox").fill(marketSlug);
    }
    await page
      .getByRole("option")
      .filter({ hasText: `Will ${marketSlug} happen?` })
      .click();
    await page.getByRole("button", { name: ONBOARDING_COPY.REVIEW, exact: true }).click();
    await expect(page.getByText(ONBOARDING_COPY.NO_LAUNCH, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: ONBOARDING_COPY.BACK, exact: true }).click();
    await expect(page.getByLabel("Name", { exact: true })).toHaveValue(`Guided ${scenario}`);
    await page.getByRole("button", { name: ONBOARDING_COPY.REVIEW, exact: true }).click();
    await page.getByRole("button", { name: ONBOARDING_COPY.SAVE, exact: true }).click();
    await expect(page).toHaveURL(/\/bots\/[a-f0-9-]+$/);
    expect(await (await page.request.get(contract.apiPaths.runs)).json()).toEqual([]);
    await page.getByRole("button", { name: BOT_DETAIL_COPY.RUN, exact: true }).click();
    await expect(page).toHaveURL(/\/runs\/[a-f0-9-]+$/);
    const guide = page.getByRole("region", { name: RUN_GUIDE_COPY.HEADING });
    await expect(guide).toContainText(expected.guidance, { timeout: RUN_READY_TIMEOUT_MS });
    await expect(guide).toContainText(`${RUN_GUIDE_COPY.LOADED_FILLS}: ${expectedFillCount}`);
    await expect(guide).toContainText(RUN_GUIDE_COPY.BALANCES);
    expect(await horizontalOverflowingElements(page)).toEqual([]);
    await page
      .getByRole("button", { name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!, exact: true })
      .click();
    await expect(guide).toContainText(RUN_GUIDE_COPY.STOPPED, { timeout: RUN_READY_TIMEOUT_MS });
    await page.reload();
    await expect(guide).toContainText(RUN_GUIDE_COPY.STOPPED, { timeout: RUN_READY_TIMEOUT_MS });
    await expect(guide).toContainText(`${RUN_GUIDE_COPY.LOADED_FILLS}: ${expectedFillCount}`);
  });
}

async function horizontalOverflowingElements(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter((element) => {
        const bounds = element.getBoundingClientRect();
        return bounds.width > 0 && bounds.right > window.innerWidth + 1;
      })
      .map((element) => `${element.tagName}.${element.className}`),
  );
}
