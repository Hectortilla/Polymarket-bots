import { SELECTION_SEARCH_COPY } from "./selectionSearch/copy";
import { lookupWallets, searchWallets, type WalletSuggestion } from "$lib/api/generated";
import catalogContract from "./catalogContract.fixture.json";
import type { SelectionSource, SelectionSuggestion } from "./selectionSearch";

export const walletSelection: SelectionSource = {
  limits: catalogContract.walletSearch,
  copy: {
    PLACEHOLDER: "Search wallets by name or 0x address…",
    NO_RESULTS: "No wallets found. Try another name or paste a full wallet address.",
    SEARCH_ERROR: "Wallet search is unavailable. Please try again.",
    ...SELECTION_SEARCH_COPY,
    UNAVAILABLE: "Wallet unavailable",
    MISSING: "Wallet details unavailable",
    LOOKUP_ERROR: "Selected wallet details could not be loaded. Your selections are preserved.",
    TYPE_HINT: `Type at least ${catalogContract.walletSearch.minimumQueryLength} characters to find a wallet.`,
    RESULTS_LABEL: "Wallet search results",
    SELECTED_LABEL: "Selected wallets",
    SELECTION_HINT: "Search by name or paste a wallet address. You can select multiple wallets.",
  },
  async search(q, signal) {
    const { data } = await searchWallets({
      query: { q, limit: catalogContract.walletSearch.defaultLimit },
      signal,
      throwOnError: true,
    });
    return { items: data.wallets.map(suggestion), has_more: data.has_more };
  },
  async lookup(addresses, signal) {
    const { data } = await lookupWallets({ body: { addresses }, signal, throwOnError: true });
    return data.map(suggestion);
  },
};

function suggestion(wallet: WalletSuggestion): SelectionSuggestion {
  return { id: wallet.address, title: wallet.name ?? wallet.address };
}
