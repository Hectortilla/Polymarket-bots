import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TEST_GRAPH, TEST_GRAPH_CATALOG } from "$lib/catalog/nodeGraphTestFixtures";
import { BOT_DEFINITION_LABEL, SELECTION_MODE } from "$lib/catalog/schema";
import contract from "$lib/runtimeContract.fixture.json";
import { RESOURCE_LIMIT_DETAIL } from "$lib/limits/testFixtures";
import { ONBOARDING_COPY } from "./copy";
import { DRAFT_SAVE_UNCERTAIN_COPY } from "$lib/bots/savedDraft/feedback";
import { HTTP_STATUS } from "$lib/api/http";
import { NAVIGATION_LABEL, NAVIGATION_PATH } from "$lib/navigation";

const mocks = vi.hoisted(() => ({
  definitions: vi.fn(),
  template: vi.fn(),
  bot: vi.fn(),
  usage: vi.fn(),
  goto: vi.fn(),
}));
vi.mock("$app/navigation", () => ({ goto: mocks.goto }));
vi.mock("$lib/api/generated", () => ({
  listBotDefinitionsApiV1BotDefinitionsGet: mocks.definitions,
  createGraphTemplateApiV1GraphTemplatesPost: mocks.template,
  createBotApiV1BotsPost: mocks.bot,
  readUsage: mocks.usage,
}));
import GuidedBot from "./GuidedBot.svelte";

const definition = {
  definition_id: "test-example",
  display_name: "Test graph",
  description: "A fixture",
  label: BOT_DEFINITION_LABEL.STANDARD,
  market_selection: SELECTION_MODE.USER_CONFIGURED,
  wallet_selection: SELECTION_MODE.ABSENT,
  graph_catalog: TEST_GRAPH_CATALOG,
  starter_graph: TEST_GRAPH,
  graph_examples: [{ name: "Example one", description: "Waits for an entry condition", graph: TEST_GRAPH }],
  input_schema: { type: "object", required: ["name"], properties: { name: { type: "string", minLength: 1 } } },
};
beforeEach(() => {
  mocks.definitions.mockResolvedValue({ data: [definition] });
  mocks.usage.mockResolvedValue({
    data: {
      policy: contract.resourcePolicy,
      active_runs: 0,
      queued_runs: 0,
      saved_bots: 0,
      saved_templates: 0,
      retained_runs: 0,
    },
  });
  mocks.template.mockResolvedValue({ data: { id: "private-template" } });
  mocks.bot.mockResolvedValue({ data: { id: "private-bot" } });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

async function review(): Promise<void> {
  await fireEvent.click(await screen.findByRole("button", { name: ONBOARDING_COPY.CONTINUE }));
  await fireEvent.input(screen.getByLabelText("Name"), { target: { value: "My example" } });
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.REVIEW }));
  await screen.findByRole("button", { name: ONBOARDING_COPY.SAVE });
}

it("loads examples with retry and preserves a route back to existing bots", async () => {
  mocks.definitions.mockRejectedValueOnce(new Error("offline"));
  render(GuidedBot);
  expect(screen.getByText(ONBOARDING_COPY.LOADING)).toBeTruthy();
  expect(await screen.findByRole("alert")).toHaveTextContent(ONBOARDING_COPY.LOAD_ERROR);
  expect(screen.getByRole("link", { name: NAVIGATION_LABEL.BACK_TO_BOTS })).toHaveAttribute(
    "href",
    NAVIGATION_PATH.HOME,
  );
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.RETRY }));
  expect(await screen.findByRole("radio")).toBeChecked();
});
it("does not persist before review, retains settings on Back, and saves without launch", async () => {
  render(GuidedBot);
  await review();
  expect(mocks.template).not.toHaveBeenCalled();
  expect(mocks.bot).not.toHaveBeenCalled();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.BACK }));
  expect(screen.getByLabelText("Name")).toHaveValue("My example");
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.REVIEW }));
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  await waitFor(() => expect(mocks.goto).toHaveBeenCalled());
  expect(mocks.bot).toHaveBeenCalledWith(
    expect.objectContaining({
      body: {
        definition_id: definition.definition_id,
        inputs: { name: "My example" },
        graph_template_id: "private-template",
      },
    }),
  );
});
it("retains the review after capacity rejection and reuses the confirmed template", async () => {
  mocks.bot.mockRejectedValueOnce({
    code: Object.values(contract.resourceLimitCodes)[0],
    detail: RESOURCE_LIMIT_DETAIL,
  });
  render(GuidedBot);
  await review();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  expect(await screen.findByRole("alert")).toHaveTextContent(RESOURCE_LIMIT_DETAIL);
  expect(screen.getByText("My example")).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  await waitFor(() => expect(mocks.goto).toHaveBeenCalled());
  expect(mocks.template).toHaveBeenCalledTimes(1);
});

it("retries navigation without repeating a confirmed bot write", async () => {
  mocks.goto.mockRejectedValueOnce(new Error("navigation failed"));
  render(GuidedBot);
  await review();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  expect(await screen.findByRole("alert")).toHaveTextContent(ONBOARDING_COPY.SAVE_ERROR);
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  await waitFor(() => expect(mocks.goto).toHaveBeenCalledTimes(2));
  expect(mocks.bot).toHaveBeenCalledTimes(1);
});
it("returns authoritative field errors to settings without losing entered values", async () => {
  mocks.bot.mockResolvedValueOnce({
    error: { detail: [{ loc: ["body", "inputs", "name"], msg: "Name was rejected", type: "value_error" }] },
    response: new Response(null, { status: HTTP_STATUS.UNPROCESSABLE_CONTENT }),
  });
  render(GuidedBot);
  await review();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  await waitFor(() => expect(screen.getByLabelText("Name")).toBeVisible());
  expect(screen.getByLabelText("Name")).toHaveValue("My example");
  expect(screen.getByText("Name was rejected.")).toBeVisible();
  expect(mocks.goto).not.toHaveBeenCalled();
});
it("keeps choices visible and blocks blind retries after an uncertain write", async () => {
  mocks.bot.mockRejectedValueOnce(new TypeError("network lost"));
  render(GuidedBot);
  await review();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  expect(await screen.findByRole("alert")).toHaveTextContent(DRAFT_SAVE_UNCERTAIN_COPY);
  expect(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE })).toBeDisabled();
  expect(screen.getByText("My example")).toBeVisible();
  expect(mocks.goto).not.toHaveBeenCalled();
});
it.each([{ definitions: [] }, { definitions: [{ ...definition, graph_examples: [] }] }])(
  "rejects an unusable successful catalog response",
  async ({ definitions }) => {
    mocks.definitions.mockResolvedValue({ data: definitions });
    render(GuidedBot);
    expect(await screen.findByRole("alert")).toHaveTextContent(ONBOARDING_COPY.LOAD_ERROR);
    expect(screen.getByRole("button", { name: ONBOARDING_COPY.RETRY })).toBeEnabled();
  },
);
it("reviews and saves the selected second example", async () => {
  const second = {
    name: "Example two",
    description: "A second set of conditions",
    graph: { ...TEST_GRAPH, parameters: [] },
  };
  mocks.definitions.mockResolvedValue({
    data: [{ ...definition, graph_examples: [...definition.graph_examples, second] }],
  });
  render(GuidedBot);
  await fireEvent.click(await screen.findByRole("radio", { name: new RegExp(second.name) }));
  await review();
  expect(screen.getByRole("heading", { name: second.name })).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  await waitFor(() =>
    expect(mocks.template).toHaveBeenCalledWith(
      expect.objectContaining({ body: expect.objectContaining({ graph: second.graph }) }),
    ),
  );
});

it("renders a template graph rejection and retries without writing a bot first", async () => {
  mocks.template.mockResolvedValueOnce({
    error: { detail: [{ loc: ["body", "graph"], msg: "Graph input cardinality is invalid", type: "value_error" }] },
    response: new Response(null, { status: HTTP_STATUS.UNPROCESSABLE_CONTENT }),
  });
  render(GuidedBot);
  await review();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Graph input cardinality is invalid.");
  expect(mocks.bot).not.toHaveBeenCalled();
  await fireEvent.click(screen.getByRole("button", { name: ONBOARDING_COPY.SAVE }));
  await waitFor(() => expect(mocks.bot).toHaveBeenCalledTimes(1));
});
