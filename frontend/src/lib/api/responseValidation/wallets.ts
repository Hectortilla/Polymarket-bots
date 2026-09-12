import { isArrayOf, isNonemptyString } from "$lib/valueGuards";
import { isWalletAddress } from "$lib/wallets";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";

export function isWalletSuggestion(value: Record<string, unknown>): boolean {
  return (
    isWalletAddress(value.address) &&
    value.address === value.address.toLowerCase() &&
    (value.name === null || isNonemptyString(value.name))
  );
}

export function isWalletSearchResults(value: Record<string, unknown>): boolean {
  return (
    Array.isArray(value.wallets) &&
    isArrayOf(value.wallets, isWalletSuggestion) &&
    value.wallets.length <= catalogContract.walletSearch.maximumLimit &&
    new Set(value.wallets.map((wallet) => wallet.address)).size === value.wallets.length &&
    typeof value.has_more === "boolean"
  );
}
