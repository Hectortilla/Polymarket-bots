import { describe, expect, it, vi } from "vitest";
import { isWalletSearchResults } from "./wallets";
import { configureApiResponseValidation } from "./index";
import { searchWallets, lookupWallets } from "$lib/api/generated";
import { client } from "$lib/api/generated/client.gen";

const wallet = { address: `0x${"ab".repeat(20)}`, name: "Trader" };
describe("wallet response validation", () => {
  it.each([
    { wallets: [{ ...wallet, address: "wrong" }], has_more: false },
    { wallets: [{ ...wallet, name: 1 }], has_more: false },
    { wallets: [wallet, wallet], has_more: false },
    { wallets: [wallet] },
  ])("rejects malformed or duplicate wallet suggestions", (data) => {
    expect(isWalletSearchResults(data)).toBe(false);
  });
  it("accepts generated search and hydration operations", async () => {
    configureApiResponseValidation();
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ wallets: [wallet], has_more: false }))
      .mockResolvedValueOnce(Response.json([wallet]));
    client.setConfig({ baseUrl: "http://localhost", fetch });
    expect((await searchWallets({ query: { q: "Trader" }, throwOnError: true })).data.wallets).toEqual([wallet]);
    expect((await lookupWallets({ body: { addresses: [wallet.address] }, throwOnError: true })).data).toEqual([wallet]);
  });
});
