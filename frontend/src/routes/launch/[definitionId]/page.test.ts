import { HTTP_STATUS } from "$lib/api/http";
import { RESOURCE_LIMIT_CASES, RESOURCE_LIMIT_DETAIL } from "$lib/limits/testFixtures";
import { DRAFT_SAVE_UNCERTAIN_COPY } from "$lib/bots/savedDraft/feedback";
import { BOT_BUILDER_COPY } from "$lib/bots/copy";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BotDefinitionDescriptor, BotRead } from "$lib/api/generated";
import { TEST_GRAPH, TEST_GRAPH_CATALOG } from "$lib/catalog/nodeGraphTestFixtures";
import { BOT_DEFINITION_LABEL, SELECTION_MODE } from "$lib/catalog/schema";
import runtimeContract from "$lib/runtimeContract.fixture.json";
const mocks = vi.hoisted(() => ({
  createBot: vi.fn(),
  goto: vi.fn(),
  listBots: vi.fn(),
  listDefinitions: vi.fn(),
}));
vi.mock("$app/navigation", () => ({ goto: mocks.goto }));
vi.mock("$lib/api/generated", () => ({
  createBotApiV1BotsPost: mocks.createBot,
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.listDefinitions,
  listBotsApiV1BotsGet: mocks.listBots,
}));
import Page from "./+page.svelte";
const DEFINITION = {
  definition_id: "node-based-bot",
  display_name: "Node-Based Bot",
  description: "Visually compose and run a paper-trading event graph.",
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.USER_CONFIGURED,
  wallet_selection: SELECTION_MODE.ABSENT,
  graph_catalog: TEST_GRAPH_CATALOG,
  starter_graph: TEST_GRAPH,
  input_schema: {
    type: "object",
    additionalProperties: false,
    required: ["name"],
    properties: { name: { type: "string", minLength: 1 } },
  },
} satisfies BotDefinitionDescriptor;
const SOURCE_BOT = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  definition_id: DEFINITION.definition_id,
  config: {
    name: "Source bot",
    stream_rules: [],
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
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function loadBuilder(bots: BotRead[] = []): void {
  mocks.listDefinitions.mockResolvedValue({ data: [DEFINITION] });
  mocks.listBots.mockResolvedValue({ data: bots });
  mocks.createBot.mockResolvedValue({
    data: { id: "eeeeeeee-0000-0000-0000-000000000001" },
  });
}
describe("unified bot creation page", () => {
  it("creates the graph copy and configured bot from one form", async () => {
    loadBuilder();
    render(Page);
    await fireEvent.input(await screen.findByLabelText("Name"), {
      target: { value: "Threshold buyer" },
    });
    await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
    await waitFor(() => {
      expect(mocks.createBot).toHaveBeenCalledWith({
        body: {
          definition_id: DEFINITION.definition_id,
          inputs: { name: "Threshold buyer" },
          graph: expect.any(Object),
        },
      });
    });
    expect(mocks.goto).toHaveBeenCalledWith("/bots/eeeeeeee-0000-0000-0000-000000000001");
  });
  it("offers existing bots as graph starting points without exposing templates", async () => {
    loadBuilder([SOURCE_BOT]);
    render(Page);
    const source = await screen.findByLabelText("Starting point");
    await fireEvent.change(source, { target: { value: SOURCE_BOT.id } });
    await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.COPY_GRAPH }));
    expect(screen.getByText(/Current source: Source bot/)).toBeTruthy();
    expect(screen.queryByText("Graph template")).toBeNull();
  });
  it("reports a missing graph-capable definition instead of offering bot types", async () => {
    mocks.listDefinitions.mockResolvedValue({ data: [] });
    mocks.listBots.mockResolvedValue({ data: [] });
    render(Page);
    expect((await screen.findByRole("alert")).textContent).toContain(BOT_BUILDER_COPY.MISSING_DEFINITION);
    expect(screen.queryByLabelText("Name")).toBeNull();
  });
  it.each(RESOURCE_LIMIT_CASES)("preserves the entered configuration when creation fails", async (code) => {
    loadBuilder();
    mocks.createBot.mockRejectedValue(code ? { code, detail: RESOURCE_LIMIT_DETAIL } : new Error("write failed"));
    render(Page);
    const name = await screen.findByLabelText("Name");
    await fireEvent.input(name, { target: { value: "Keep my draft" } });
    await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      code ? RESOURCE_LIMIT_DETAIL : DRAFT_SAVE_UNCERTAIN_COPY,
    );
    expect((name as HTMLInputElement).value).toBe("Keep my draft");
  });
});
it("reuses a saved draft when retrying a bot allowance failure", async () => {
  loadBuilder();
  mocks.createBot.mockRejectedValueOnce({ code: RESOURCE_LIMIT_CASES[1], detail: RESOURCE_LIMIT_DETAIL });
  render(Page);
  await fireEvent.input(await screen.findByLabelText("Name"), { target: { value: "Retry setup" } });
  await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
  expect(await screen.findByRole("alert")).toHaveTextContent(RESOURCE_LIMIT_DETAIL);
  await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
  await waitFor(() => expect(mocks.goto).toHaveBeenCalled());
  expect(mocks.createBot).toHaveBeenCalledTimes(2);
});

it("disables resending a resolved server error while preserving the draft", async () => {
  loadBuilder();
  mocks.createBot.mockResolvedValueOnce({
    error: {},
    response: new Response(null, { status: HTTP_STATUS.INTERNAL_SERVER_ERROR }),
  });
  render(Page);
  await fireEvent.input(await screen.findByLabelText("Name"), { target: { value: "Uncertain draft" } });
  const save = screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE });
  await fireEvent.click(save);
  expect(await screen.findByRole("alert")).toHaveTextContent(DRAFT_SAVE_UNCERTAIN_COPY);
  expect(save).toBeDisabled();
  await fireEvent.click(save);
  expect(mocks.createBot).toHaveBeenCalledTimes(1);
});
it("focuses a rejected bot graph and allows a corrected retry", async () => {
  loadBuilder();
  mocks.createBot.mockResolvedValueOnce({
    error: { detail: [{ loc: ["body", "graph"], msg: "Graph input cardinality is invalid", type: "value_error" }] },
    response: new Response(null, { status: HTTP_STATUS.UNPROCESSABLE_CONTENT }),
  });
  render(Page);
  await fireEvent.input(await screen.findByLabelText("Name"), { target: { value: "Correct my graph" } });
  await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
  expect(await screen.findByText("Graph input cardinality is invalid.")).toBeTruthy();
  await waitFor(() => expect(document.getElementById("new-bot-graph-validation")).toHaveFocus());
  expect(mocks.createBot).toHaveBeenCalledTimes(1);
  await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
  await waitFor(() => expect(mocks.createBot).toHaveBeenCalledTimes(2));
});
it("renders bot input rejection on the full editor without a generic save error", async () => {
  loadBuilder();
  mocks.createBot.mockResolvedValueOnce({
    error: { detail: [{ loc: ["body", "inputs", "name"], msg: "Name was rejected", type: "value_error" }] },
    response: new Response(null, { status: HTTP_STATUS.UNPROCESSABLE_CONTENT }),
  });
  render(Page);
  const name = await screen.findByLabelText("Name");
  await fireEvent.input(name, { target: { value: "Keep this value" } });
  await fireEvent.click(screen.getByRole("button", { name: BOT_BUILDER_COPY.CREATE }));
  expect(await screen.findByText("Name was rejected.")).toBeTruthy();
  expect(name).toHaveValue("Keep this value");
  expect(screen.queryByText(BOT_BUILDER_COPY.SAVE_ERROR)).toBeNull();
});
