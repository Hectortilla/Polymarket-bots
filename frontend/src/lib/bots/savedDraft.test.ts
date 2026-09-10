import { HTTP_STATUS } from "$lib/api/http";
import { afterEach, expect, it, vi } from "vitest";
import { DRAFT_WRITE } from "./savedDraft/failure";
import contract from "$lib/runtimeContract.fixture.json";
import { TEST_GRAPH } from "$lib/catalog/nodeGraphTestFixtures";
const mocks = vi.hoisted(() => ({ template: vi.fn(), bot: vi.fn() }));
vi.mock("$lib/api/generated", () => ({
  createGraphTemplateApiV1GraphTemplatesPost: mocks.template,
  createBotApiV1BotsPost: mocks.bot,
}));
import { SavedBotDraft } from "./savedDraft";
afterEach(() => vi.resetAllMocks());
it("reuses confirmed template after bot failure and confirmed bot after navigation failure", async () => {
  mocks.template.mockResolvedValue({ data: { id: "private-template" } });
  mocks.bot
    .mockRejectedValueOnce({ code: contract.resourceLimitCodes.USER_ALLOWANCE, detail: "capacity" })
    .mockResolvedValue({ data: { id: "saved-bot" } });
  const draft = new SavedBotDraft();
  await expect(draft.save("example-definition", { name: "First" }, TEST_GRAPH)).rejects.toMatchObject({
    uncertain: false,
  });
  const bot = await draft.save("example-definition", { name: "First" }, TEST_GRAPH);
  expect(await draft.save("example-definition", { name: "First" }, TEST_GRAPH)).toBe(bot);
  expect(mocks.template).toHaveBeenCalledTimes(1);
  expect(mocks.bot).toHaveBeenCalledTimes(2);
  await draft.save("example-definition", { name: "Changed" }, TEST_GRAPH);
  expect(mocks.template).toHaveBeenCalledTimes(1);
  expect(mocks.bot).toHaveBeenCalledTimes(3);
});
it("creates a new private template when the selected graph changes", async () => {
  mocks.template.mockResolvedValue({ data: { id: "private-template" } });
  mocks.bot.mockResolvedValue({ data: { id: "saved-bot" } });
  const draft = new SavedBotDraft();
  await draft.save("example-definition", {}, TEST_GRAPH);
  await draft.save("example-definition", {}, { ...TEST_GRAPH, parameters: [] });
  expect(mocks.template).toHaveBeenCalledTimes(2);
});

it.each(Object.values(DRAFT_WRITE))("never resends an uncertain %s write in the current draft", async (stage) => {
  mocks.template.mockResolvedValue({ data: { id: "private-template" } });
  mocks.bot.mockResolvedValue({ data: { id: "saved-bot" } });
  mocks[stage].mockRejectedValueOnce(new TypeError("response lost"));
  const draft = new SavedBotDraft();
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  expect(mocks[stage]).toHaveBeenCalledTimes(1);
});

it.each(
  Object.values(DRAFT_WRITE).flatMap((stage) =>
    [HTTP_STATUS.INTERNAL_SERVER_ERROR, undefined].map((status) => ({ stage, status })),
  ),
)("fences a resolved uncertain $stage write (status=$status)", async ({ stage, status }) => {
  mocks.template.mockResolvedValue({ data: { id: "private-template" } });
  mocks.bot.mockResolvedValue({ data: { id: "saved-bot" } });
  mocks[stage].mockResolvedValueOnce({
    error: new TypeError("fetch failed"),
    response: status === undefined ? undefined : new Response(null, { status }),
  });
  const draft = new SavedBotDraft();
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  expect(mocks[stage]).toHaveBeenCalledTimes(1);
});
