import { isArrayOf, isNonemptyString, isFiniteDateTime } from "$lib/valueGuards";
import catalogContract from "$lib/catalog/catalogContract.fixture.json";

export function isMarketSuggestion(value: Record<string, unknown>): boolean {
  return (
    isNonemptyString(value.slug) &&
    isNonemptyString(value.condition_id) &&
    isNonemptyString(value.question) &&
    (value.event_title === null || isNonemptyString(value.event_title)) &&
    (value.end_date === null || isFiniteDateTime(value.end_date)) &&
    typeof value.is_open_for_trading === "boolean"
  );
}

export function isMarketSearchResults(value: Record<string, unknown>): boolean {
  return (
    Array.isArray(value.markets) &&
    isArrayOf(value.markets, isMarketSuggestion) &&
    value.markets.length <= catalogContract.marketSearch.maximumLimit &&
    value.markets.every((market) => market.is_open_for_trading === true) &&
    typeof value.has_more === "boolean"
  );
}
