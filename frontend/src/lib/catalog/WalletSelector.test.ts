import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { lookupWallets, searchWallets, type WalletSuggestion } from "$lib/api/generated";
import WalletSelector from "./WalletSelector.svelte";
import catalogContract from "./catalogContract.fixture.json";

vi.mock("$lib/api/generated", () => ({ searchWallets: vi.fn(), lookupWallets: vi.fn() }));
const wallet = { address: `0x${"ab".repeat(20)}`, name: "Trader" };
function results(wallets: WalletSuggestion[] = [wallet]) {
  return { data: { wallets, has_more: false } } as Awaited<ReturnType<typeof searchWallets<true>>>;
}
beforeEach(() => {
  vi.mocked(searchWallets).mockReset().mockResolvedValue(results());
  vi.mocked(lookupWallets)
    .mockReset()
    .mockResolvedValue({ data: [wallet] } as Awaited<ReturnType<typeof lookupWallets>>);
});
afterEach(cleanup);
async function search(q: string) {
  const input = screen.getByRole("combobox");
  await fireEvent.focus(input);
  await fireEvent.input(input, { target: { value: q } });
  return input;
}
describe("WalletSelector", () => {
  it("debounces names and selects canonical addresses with the keyboard", async () => {
    const onchange = vi.fn();
    render(WalletSelector, { value: [], onchange, labelId: "wallets" });
    await search("Tra");
    const input = await search("Trader");
    expect(searchWallets).not.toHaveBeenCalled();
    await screen.findByRole("option", { name: /Trader/ });
    expect(searchWallets).toHaveBeenCalledTimes(1);
    await fireEvent.keyDown(input, { key: "ArrowDown" });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(onchange).toHaveBeenCalledWith([wallet.address]);
  });
  it("sends address IDs to the backend and never commits unselected search text", async () => {
    const onchange = vi.fn();
    render(WalletSelector, { value: [], onchange, labelId: "wallets" });
    await search(wallet.address);
    await screen.findByRole("option", { name: /Trader/ });
    expect(searchWallets).toHaveBeenCalledWith(
      expect.objectContaining({ query: { q: wallet.address, limit: catalogContract.walletSearch.defaultLimit } }),
    );
    expect(onchange).not.toHaveBeenCalled();
  });
  it("hydrates saved wallets, prevents duplicates and removes selections", async () => {
    const onchange = vi.fn();
    render(WalletSelector, { value: [wallet.address], onchange, labelId: "wallets" });
    await screen.findByRole("button", { name: "Remove Trader" });
    expect(lookupWallets).toHaveBeenCalledWith(expect.objectContaining({ body: { addresses: [wallet.address] } }));
    await search("Trader");
    await fireEvent.click(await screen.findByRole("option", { name: /Trader/ }));
    expect(onchange).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "Remove Trader" }));
    expect(onchange).toHaveBeenCalledWith([]);
  });
  it("cancels old requests and ignores late name results", async () => {
    let finish!: (result: Awaited<ReturnType<typeof searchWallets<true>>>) => void;
    vi.mocked(searchWallets).mockImplementationOnce(
      () =>
        new Promise<Awaited<ReturnType<typeof searchWallets<true>>>>((resolve) => {
          finish = resolve;
        }),
    );
    render(WalletSelector, { value: [], onchange: vi.fn(), labelId: "wallets" });
    await search("old");
    await waitFor(() => expect(searchWallets).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(searchWallets).mock.calls[0][0].signal!;
    await search("new");
    expect(signal.aborted).toBe(true);
    await screen.findByRole("option", { name: /Trader/ });
    finish(results([{ ...wallet, name: "Stale" }]));
    await Promise.resolve();
    expect(screen.queryByRole("option", { name: /Stale/ })).toBeNull();
  });
});

it("uses an unnamed wallet address in search results and saved removable chips", async () => {
  const unnamed = { ...wallet, name: null };
  vi.mocked(searchWallets).mockResolvedValue(results([unnamed]));
  vi.mocked(lookupWallets).mockResolvedValue({ data: [unnamed] } as Awaited<ReturnType<typeof lookupWallets>>);
  const onchange = vi.fn();
  const mounted = render(WalletSelector, { value: [], onchange, labelId: "wallets" });
  await search(unnamed.address);
  await fireEvent.click(await screen.findByRole("option", { name: new RegExp(unnamed.address) }));
  expect(onchange).toHaveBeenCalledWith([unnamed.address]);
  await mounted.rerender({ value: [unnamed.address], onchange, labelId: "wallets" });
  await fireEvent.click(await screen.findByRole("button", { name: `Remove ${unnamed.address}` }));
  expect(onchange).toHaveBeenLastCalledWith([]);
});
