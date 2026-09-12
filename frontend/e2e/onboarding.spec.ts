import { SELECTION_SEARCH_COPY } from "../src/lib/catalog/selectionSearch/copy";
import { test, expect, type Page } from "@playwright/test";
import fixture from "./onboardingContract.fixture.json" with { type: "json" };
import browserContract from "./accountContract.fixture.json" with { type: "json" };
import contract from "../src/lib/runtimeContract.fixture.json" with { type: "json" };
import { completeEmailVerification } from "./accountLinkFlows";
import { AUTH_COPY } from "../src/lib/auth/copy";
import { REGISTER_PATH } from "../src/lib/auth/navigation";
import { NAVIGATION_PATH } from "../src/lib/navigation";
import { ONBOARDING_COPY } from "../src/lib/onboarding/copy";
import { RUN_DETAIL_COPY } from "../src/routes/runs/[runId]/copy";
import { RUN_GUIDE_COPY } from "../src/lib/runs/runGuide";
import { BOT_DETAIL_COPY } from "../src/routes/bots/[botId]/copy";
import { MARKET_SELECTOR_COPY } from "../src/lib/catalog/copy";
import { HTTP_STATUS } from "../src/lib/api/http";
import { RUN_STATUS, RUN_STATUS_PRESENTATION } from "../src/lib/runs/status";

const RUN_READY_TIMEOUT_MS = 20_000;

const expectations = {
  action: { recoverSearch: true },
  waiting: { recoverSearch: false },
} satisfies Record<keyof typeof fixture.cases, { recoverSearch: boolean }>;

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
    await completeEmailVerification(page, email, password);
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
      await page.getByRole("combobox", { name: browserContract.selectorLabels.markets, exact: true }).fill(marketSlug);
      await expect(page.getByText(MARKET_SELECTOR_COPY.SEARCH_ERROR, { exact: true })).toBeVisible();
      await page.getByRole("button", { name: SELECTION_SEARCH_COPY.RETRY_SEARCH, exact: true }).click();
      await expect(page.getByLabel("Name", { exact: true })).toHaveValue(`Guided ${scenario}`);
    } else {
      await page.getByRole("combobox", { name: browserContract.selectorLabels.markets, exact: true }).fill(marketSlug);
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
    await page.getByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }).click();
    await expect(page.getByText(RUN_GUIDE_COPY.BOOK_REPORTED, { exact: true })).toBeVisible({
      timeout: RUN_READY_TIMEOUT_MS,
    });
    await expect(page.getByText(/shares filled/)).toHaveCount(expectedFillCount, { timeout: RUN_READY_TIMEOUT_MS });
    expect(await horizontalOverflowingElements(page)).toEqual([]);
    await page
      .getByRole("button", { name: RUN_STATUS_PRESENTATION[RUN_STATUS.RUNNING].stopLabel!, exact: true })
      .click();
    await expect(
      page.getByText(RUN_STATUS_PRESENTATION[RUN_STATUS.STOPPED].label, { exact: true }).first(),
    ).toBeVisible({ timeout: RUN_READY_TIMEOUT_MS });
    await page.reload();
    await page.getByRole("button", { name: RUN_DETAIL_COPY.SHOW_EVENTS }).click();
    await expect(
      page.getByText(RUN_STATUS_PRESENTATION[RUN_STATUS.STOPPED].label, { exact: true }).first(),
    ).toBeVisible({ timeout: RUN_READY_TIMEOUT_MS });
    await expect(page.getByText(/shares filled/)).toHaveCount(expectedFillCount);
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
