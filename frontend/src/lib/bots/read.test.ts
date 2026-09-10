import { afterEach, expect, it, vi } from "vitest";
import { HTTP_STATUS } from "$lib/api/http";
import { BotNotFoundError, readSavedBot } from "./read";

const mocks = vi.hoisted(() => ({ readBotApiV1BotsBotIdGet: vi.fn() }));
vi.mock("$lib/api/generated", () => mocks);
afterEach(() => vi.clearAllMocks());

it("normalizes inaccessible bots into the not-found domain result", async () => {
  mocks.readBotApiV1BotsBotIdGet.mockResolvedValue({ response: { status: HTTP_STATUS.NOT_FOUND } });
  await expect(readSavedBot("bot")).rejects.toBeInstanceOf(BotNotFoundError);
});

it("keeps infrastructure failure distinct from missing resources", async () => {
  mocks.readBotApiV1BotsBotIdGet.mockResolvedValue({ response: { status: HTTP_STATUS.SERVICE_UNAVAILABLE } });
  await expect(readSavedBot("bot")).rejects.toThrow("Saved bot unavailable");
});
