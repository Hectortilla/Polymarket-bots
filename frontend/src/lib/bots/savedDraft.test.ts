import { HTTP_STATUS } from "$lib/api/http";
import { afterEach, expect, it, vi } from "vitest";
import contract from "$lib/runtimeContract.fixture.json";
import { TEST_GRAPH } from "$lib/catalog/nodeGraphTestFixtures";
const mocks = vi.hoisted(() => ({ bot: vi.fn() }));
vi.mock("$lib/api/generated", () => ({ createBotApiV1BotsPost: mocks.bot }));
import { SavedBotDraft } from "./savedDraft";
afterEach(() => vi.resetAllMocks());

it("saves settings and graph in one request and reuses a confirmed save", async () => {
  mocks.bot.mockResolvedValue({ data: { id: "saved-bot" } });
  const draft = new SavedBotDraft();
  const saved = await draft.save("example-definition", { name: "First" }, TEST_GRAPH);
  expect(mocks.bot).toHaveBeenCalledExactlyOnceWith({
    body: { definition_id: "example-definition", inputs: { name: "First" }, graph: TEST_GRAPH },
  });
  expect(await draft.save("example-definition", { name: "First" }, TEST_GRAPH)).toBe(saved);
  expect(mocks.bot).toHaveBeenCalledTimes(1);
});

it("allows a corrected retry after a confirmed rejection", async () => {
  mocks.bot
    .mockRejectedValueOnce({ code: contract.resourceLimitCodes.USER_ALLOWANCE, detail: "capacity" })
    .mockResolvedValue({ data: { id: "saved-bot" } });
  const draft = new SavedBotDraft();
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: false });
  await draft.save("example-definition", { name: "Corrected" }, TEST_GRAPH);
  expect(mocks.bot).toHaveBeenCalledTimes(2);
});

it("never resends a write after a lost response", async () => {
  mocks.bot.mockRejectedValueOnce(new TypeError("response lost"));
  const draft = new SavedBotDraft();
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  expect(mocks.bot).toHaveBeenCalledTimes(1);
});

it.each([HTTP_STATUS.INTERNAL_SERVER_ERROR, undefined])("fences an uncertain save (status=%s)", async (status) => {
  mocks.bot.mockResolvedValueOnce({
    error: new TypeError("fetch failed"),
    response: status === undefined ? undefined : new Response(null, { status }),
  });
  const draft = new SavedBotDraft();
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  await expect(draft.save("example-definition", {}, TEST_GRAPH)).rejects.toMatchObject({ uncertain: true });
  expect(mocks.bot).toHaveBeenCalledTimes(1);
});
