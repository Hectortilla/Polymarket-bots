import type { Side, ValuationStatus } from '$lib/api/generated';
import runtimeContract from '$lib/runtimeContract.fixture.json';

type SideContract = {
  [Key in keyof typeof runtimeContract.side]: Extract<Side, Key>;
};
type ValuationStatusContract = {
  [Key in keyof typeof runtimeContract.valuationStatus]: Extract<
    ValuationStatus,
    Lowercase<Key>
  >;
};

const sideContract = runtimeContract.side as SideContract;
const valuationStatusContract = runtimeContract.valuationStatus as ValuationStatusContract;

export const MAX_CHART_HISTORY_POINTS = runtimeContract.dashboard.maxChartHistoryPoints;
export const MAX_CHART_TOKENS = runtimeContract.dashboard.maxChartTokens;
export const MAX_WALLET_TIMELINE_EVENTS = runtimeContract.dashboard.maxWalletTimelineEvents;
export const MIN_TIME_ZOOM_LEVEL = runtimeContract.dashboard.minTimeZoomLevel;
export const MAX_TIME_ZOOM_LEVEL = runtimeContract.dashboard.maxTimeZoomLevel;
export const INITIAL_TIME_ZOOM_LEVEL = runtimeContract.dashboard.initialTimeZoomLevel;
export const OUTCOME_PRICE_FLOOR = Number(runtimeContract.outcomePrice.floor);
export const OUTCOME_PRICE_CEILING = Number(runtimeContract.outcomePrice.ceiling);
export const WALLET_NOTIONAL_TIER_COUNT = runtimeContract.dashboard.walletNotionalTierCount;

export const SIDE = {
  buy: sideContract.BUY,
  sell: sideContract.SELL
} as const satisfies Record<string, Side>;

export const VALUATION_STATUS = {
  fresh: valuationStatusContract.FRESH,
  stale: valuationStatusContract.STALE,
  unavailable: valuationStatusContract.UNAVAILABLE
} as const satisfies Record<string, ValuationStatus>;

export type AvailableValuationStatus = Exclude<
  ValuationStatus,
  typeof VALUATION_STATUS.unavailable
>;

export const DASHBOARD_KEY = {
  closer: runtimeContract.dashboard.keys.CLOSER,
  wider: runtimeContract.dashboard.keys.WIDER,
  reset: runtimeContract.dashboard.keys.RESET,
  view: runtimeContract.dashboard.keys.VIEW,
  nextWalletPage: runtimeContract.dashboard.keys.NEXT_WALLET_PAGE,
  previousWalletPage: runtimeContract.dashboard.keys.PREVIOUS_WALLET_PAGE
} as const;
