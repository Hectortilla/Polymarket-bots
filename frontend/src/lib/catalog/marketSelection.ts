import { lookupMarkets, searchMarkets, type MarketSuggestion } from "$lib/api/generated";
import { MARKET_SELECTOR_COPY } from "./copy";
import catalogContract from "./catalogContract.fixture.json";
import type { SelectionSource, SelectionSuggestion } from "./selectionSearch";

function suggestion(market: MarketSuggestion): SelectionSuggestion {
  return {
    id: market.slug,
    title: market.question,
    subtitle: market.event_title,
    detail: market.end_date
      ? `Ends ${new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(market.end_date))}`
      : null,
    unavailable: !market.is_open_for_trading,
  };
}

export const marketSelection: SelectionSource = {
  limits: catalogContract.marketSearch,
  copy: {
    ...MARKET_SELECTOR_COPY,
    TYPE_HINT: `Type at least ${catalogContract.marketSearch.minimumQueryLength} characters to find a market.`,
    RESULTS_LABEL: "Market search results",
    SELECTED_LABEL: "Selected markets",
    SELECTION_HINT: "Choose one or more markets. You can keep searching to add more.",
  },
  async search(q, signal) {
    const { data } = await searchMarkets({
      query: { q, limit: catalogContract.marketSearch.defaultLimit },
      signal,
      throwOnError: true,
    });
    return { items: data.markets.map(suggestion), has_more: data.has_more };
  },
  async lookup(slugs, signal) {
    const { data } = await lookupMarkets({ body: { slugs }, signal, throwOnError: true });
    return data.map(suggestion);
  },
};
