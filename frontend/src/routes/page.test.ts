import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BotRead, RunRead, StreamRelation } from "$lib/api/generated";
import { TEST_GRAPH } from "$lib/catalog/nodeGraphTestFixtures";
import { VALUATION_STATUS } from "$lib/charts/contracts";
import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath, runPath } from "$lib/navigation";
import { RUN_STATUS, runStatusLabel } from "$lib/runs/status";
import runtimeContract from "$lib/runtimeContract.fixture.json";
import { formatTime } from "$lib/time";
const mocks = vi.hoisted(() => ({
  listBots: vi.fn(),
  listRuns: vi.fn(),
}));
vi.mock("$lib/api/generated", () => ({
  listBotsApiV1BotsGet: mocks.listBots,
  listRunsApiV1RunsGet: mocks.listRuns,
}));
import Page from "./+page.svelte";
import { HOME_COLUMN_LABEL, HOME_COPY, botRowLabel, runRowLabel } from "./homeCopy";
const BOT = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  definition_id: "node-based-bot",
  config: {
    name: "BTC threshold buyer",
    stream_rules: [
      {
        relation: runtimeContract.streamRelation.INDEPENDENT as StreamRelation,
        market_slugs: ["btc-updown-5m-test"],
      },
    ],
    data_trades_budget_per_10s: runtimeContract.config.maximumDataTradesBudget,
    max_order_size: "10",
    max_slippage_pct: "0.02",
    paper_latency_ms: 250,
    paper_latency_jitter_ms: 100,
    event_max_age_ms: 5000,
    paper_portfolio_usdc: "1000",
    graph: TEST_GRAPH,
  },
  created_at: "2026-08-30T00:00:00Z",
  updated_at: "2026-08-30T00:00:00Z",
} satisfies BotRead;
const RUN = {
  id: "bbbbbbbb-0000-0000-0000-000000000001",
  bot_id: BOT.id,
  definition_id: BOT.definition_id,
  config: {
    ...BOT.config,
    graph: TEST_GRAPH,
  },
  status: RUN_STATUS.RUNNING,
  created_at: BOT.created_at,
  started_at: BOT.created_at,
  ended_at: null,
  heartbeat_at: BOT.created_at,
  failure_detail: null,
  latest_equity: "1004.25",
  equity_status: VALUATION_STATUS.fresh,
} satisfies RunRead;
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function loadHome({
  bots = [],
  runs = [],
}: {
  bots?: BotRead[];
  runs?: RunRead[];
} = {}): void {
  mocks.listBots.mockResolvedValue({ data: bots });
  mocks.listRuns.mockResolvedValue({ data: runs });
}
describe("bots home", () => {
  it("shows one direct creation action and no bot catalog", async () => {
    loadHome();
    render(Page);
    expect(screen.getByRole("heading", { name: NAVIGATION_LABEL.BOTS, level: 1 })).toBeTruthy();
    expect(await screen.findByText(HOME_COPY.CREATE_FIRST_BOT)).toBeTruthy();
    expect(screen.getByRole("link", { name: NAVIGATION_LABEL.NEW_BOT }).getAttribute("href")).toBe(
      NAVIGATION_PATH.NEW_BOT,
    );
    expect(screen.queryByText("Bot catalog")).toBeNull();
    expect(screen.queryByText("Bot workspace")).toBeNull();
    expect(screen.getByRole("heading", { name: HOME_COPY.CONFIGURED_BOTS, level: 2 })).toBeTruthy();
  });
  it("shows configured bots as scannable rows with their operational context", async () => {
    const renamedBot = { ...BOT, config: { ...BOT.config, name: "Renamed BTC buyer" } };
    loadHome({ bots: [renamedBot], runs: [RUN] });
    render(Page);
    const botLink = await screen.findByRole("link", { name: botRowLabel(renamedBot.config.name) });
    expect(botLink.getAttribute("href")).toBe(botPath(BOT.id));
    expect(within(botLink).getByText(renamedBot.config.name)).toBeTruthy();
    expect(within(botLink).getByText("btc-updown-5m-test")).toBeTruthy();
    expect(Array.from(botLink.children, (cell) => cell.getAttribute("data-label"))).toEqual([
      HOME_COLUMN_LABEL.BOT_AND_MARKETS,
      HOME_COLUMN_LABEL.LATEST_RUN,
      HOME_COLUMN_LABEL.UPDATED,
    ]);
    expect(within(botLink).getByText(runStatusLabel(RUN.status))).toBeTruthy();
    const runLink = screen.getByRole("link", {
      name: runRowLabel(RUN.config.name, formatTime(RUN.created_at)),
    });
    expect(runLink.getAttribute("href")).toBe(runPath(RUN.id));
    expect(within(runLink).getByText(RUN.config.name)).toBeTruthy();
    expect(within(runLink).getByText(RUN.config.name)).toHaveAttribute("data-label", HOME_COLUMN_LABEL.BOT_NAME);
    expect(within(runLink).queryByText(renamedBot.config.name)).toBeNull();
    expect(within(runLink).getByText(runStatusLabel(RUN.status))).toBeTruthy();
    expect(within(runLink).getByText(`${RUN.latest_equity} / ${VALUATION_STATUS.fresh}`)).toBeTruthy();
    const runTimes = runLink.querySelectorAll("time");
    expect(runTimes).toHaveLength(2);
    expect(runTimes[0]?.textContent).toBe(formatTime(RUN.created_at));
    expect(runTimes[1]?.textContent).toBe(formatTime(RUN.ended_at));
  });
  it("opens both sections by default and lets each collapse independently", async () => {
    loadHome({ bots: [BOT], runs: [RUN] });
    render(Page);
    const botsToggle = await screen.findByRole("button", { name: HOME_COPY.CONFIGURED_BOTS });
    const runsToggle = screen.getByRole("button", { name: HOME_COPY.RECENT_RUNS });
    const botLink = screen.getByRole("link", { name: botRowLabel(BOT.config.name) });
    const runLink = screen.getByRole("link", { name: runRowLabel(RUN.config.name, formatTime(RUN.created_at)) });
    expect(botsToggle).toHaveAttribute("aria-expanded", "true");
    expect(runsToggle).toHaveAttribute("aria-expanded", "true");
    await fireEvent.click(botsToggle);
    expect(botsToggle).toHaveAttribute("aria-expanded", "false");
    expect(botLink).not.toBeVisible();
    expect(runLink).toBeVisible();
    await fireEvent.click(runsToggle);
    expect(runLink).not.toBeVisible();
    await fireEvent.click(botsToggle);
    expect(botLink).toBeVisible();
    expect(runsToggle).toHaveAttribute("aria-expanded", "false");
    await fireEvent.click(runsToggle);
    expect(runLink).toBeVisible();
  });
  it("counts the displayed bots and recent runs after filtering and the history limit", async () => {
    const legacyBot = {
      ...BOT,
      id: "legacy",
      config: {
        ...BOT.config,
        graph: null,
      },
    } satisfies BotRead;
    const runs = Array.from({ length: 12 }, (_, index) => ({ ...RUN, id: `run-${index}` }));
    loadHome({ bots: [BOT, legacyBot], runs: [{ ...RUN, id: "legacy-run", bot_id: legacyBot.id }, ...runs] });
    render(Page);
    expect(await screen.findByRole("button", { name: HOME_COPY.CONFIGURED_BOTS })).toHaveAccessibleDescription(
      "1 item",
    );
    expect(screen.getByRole("button", { name: HOME_COPY.RECENT_RUNS })).toHaveAccessibleDescription("10 items");
    expect(
      screen.getAllByRole("link", { name: runRowLabel(RUN.config.name, formatTime(RUN.created_at)) }),
    ).toHaveLength(10);
  });
  it("keeps a never-run bot navigable and labels its state", async () => {
    loadHome({ bots: [BOT] });
    render(Page);
    const botLink = await screen.findByRole("link", { name: botRowLabel(BOT.config.name) });
    expect(botLink.getAttribute("href")).toBe(botPath(BOT.id));
    expect(within(botLink).getByText(HOME_COPY.NOT_RUN_YET)).toBeTruthy();
  });
  it("shows recorded failure detail on a failed recent run row", async () => {
    const runtimeFailure = "ConnectionError: market stream closed";
    const recordedFailureDetail = "ConnectionError: paper run failed";
    const failedRun = {
      ...RUN,
      status: RUN_STATUS.FAILED,
      ended_at: "2026-08-30T00:00:05Z",
      failure_detail: recordedFailureDetail,
      latest_runtime_failure: runtimeFailure,
    } satisfies RunRead;
    loadHome({ bots: [BOT], runs: [failedRun] });
    render(Page);
    const runLink = await screen.findByRole("link", {
      name: runRowLabel(failedRun.config.name, formatTime(failedRun.created_at)),
    });
    const failureDetailId = `recent-run-failure-detail-${failedRun.id}`;
    expect(runLink.getAttribute("aria-describedby")).toBe(failureDetailId);
    expect(runLink.classList.contains("failure-detail-trigger")).toBe(true);
    expect(within(runLink).getByRole("tooltip").getAttribute("id")).toBe(failureDetailId);
    expect(within(runLink).getByRole("tooltip").textContent).toContain(runtimeFailure);
    expect(within(runLink).getByRole("tooltip").textContent).toContain(`Recorded failure: ${recordedFailureDetail}`);
  });
  it("does not expose non-graph catalog bots in the operator workspace", async () => {
    const legacyBot = {
      ...BOT,
      id: "legacy",
      config: {
        ...BOT.config,
        graph: null,
      },
    } satisfies BotRead;
    loadHome({ bots: [legacyBot] });
    render(Page);
    expect(await screen.findByText(HOME_COPY.CREATE_FIRST_BOT)).toBeTruthy();
    expect(screen.queryByText(legacyBot.config.name)).toBeNull();
  });
  it("reports a failed home load without rendering partial data", async () => {
    mocks.listBots.mockRejectedValue(new Error("offline"));
    mocks.listRuns.mockResolvedValue({ data: [RUN] });
    render(Page);
    expect((await screen.findByRole("alert")).textContent).toContain(HOME_COPY.LOAD_ERROR);
    expect(screen.queryByText(RUN.config.name)).toBeNull();
  });
});
it("shows past runs of a deleted bot even when no configurations remain", async () => {
  const deletedRun = { ...RUN, status: RUN_STATUS.STOPPED, bot_deleted: true } satisfies RunRead;
  loadHome({ bots: [], runs: [deletedRun] });
  render(Page);
  const runLink = await screen.findByRole("link", { name: runRowLabel(RUN.config.name, formatTime(RUN.created_at)) });
  expect(runLink).toHaveAttribute("href", runPath(RUN.id));
  expect(screen.queryByRole("link", { name: botRowLabel(BOT.config.name) })).toBeNull();
  expect(screen.getByRole("button", { name: HOME_COPY.CONFIGURED_BOTS })).toHaveAccessibleDescription("0 items");
  expect(screen.getByRole("button", { name: HOME_COPY.RECENT_RUNS })).toHaveAccessibleDescription("1 item");
});
