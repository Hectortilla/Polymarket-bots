import type { Side, ValuationStatus } from '$lib/api/generated';

export const MAX_CHART_HISTORY_POINTS = 720;
export const MAX_CHART_TOKENS = 20;
export const MAX_WALLET_TIMELINE_EVENTS = 5_000;
export const MIN_TIME_ZOOM_LEVEL = -3;
export const MAX_TIME_ZOOM_LEVEL = 3;
export const INITIAL_TIME_ZOOM_LEVEL = 0;
export const OUTCOME_PRICE_FLOOR = 0;
export const OUTCOME_PRICE_CEILING = 1;
export const WALLET_LABEL_MAX_LENGTH = 12;
export const WALLET_NOTIONAL_TIER_COUNT = 3;

export const SIDE = {
  buy: 'BUY',
  sell: 'SELL'
} as const satisfies Record<string, Side>;

export const VALUATION_STATUS = {
  fresh: 'fresh',
  stale: 'stale',
  unavailable: 'unavailable'
} as const satisfies Record<string, ValuationStatus>;

export type AvailableValuationStatus = Exclude<
  ValuationStatus,
  typeof VALUATION_STATUS.unavailable
>;

export const DASHBOARD_KEY = {
  closer: 'z',
  wider: 'x',
  reset: 'r',
  view: 'v',
  nextWalletPage: 'j',
  previousWalletPage: 'k'
} as const;
