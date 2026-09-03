import Decimal from 'decimal.js';
import type { DispatchSkipReason, Side } from '$lib/api/generated';
import {
  MAX_CHART_TOKENS,
  MAX_WALLET_TIMELINE_EVENTS,
  SIDE,
  VALUATION_STATUS
} from '$lib/charts/contracts';
import runtimeContract from '$lib/runtimeContract.fixture.json';
import { isOutcomePrice } from '$lib/outcomePrices';
import { isSide } from '$lib/sides';
import {
  isDecimal,
  isNonemptyString,
  isNonnegativeDecimal,
  isNonnegativeInteger,
  isPositiveDecimal,
  isRecord
} from '$lib/valueGuards';

export { isNonnegativeInteger, isPositiveDecimal, isRecord } from '$lib/valueGuards';

const DISPATCH_SKIP_REASONS = new Set<DispatchSkipReason>(
  Object.values(runtimeContract.dispatchSkipReason) as DispatchSkipReason[]
);
const WALLET_SOURCE_KEY_SEPARATOR = runtimeContract.walletSourceKeySeparator;

type ValidWalletTrade = Record<string, unknown> & {
  condition_id: string;
  token_id: string;
  side: Side;
  wallet: string;
  source_id: string;
  trade_timestamp_ms: number;
  observed_at_ms: number;
  price: string;
  size: string;
  market_slug?: string | null;
  outcome?: string | null;
};

export function isChartSamplePayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && Array.isArray(payload.markets)
    && payload.markets.length <= MAX_CHART_TOKENS
    && payload.markets.every(isMarketPoint)
    && isEquityPoint(payload.equity);
}

export function isMarketChartPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && Array.isArray(payload.points)
    && payload.points.length <= MAX_CHART_TOKENS
    && payload.points.every(isMarketPoint);
}

export function isEquityChartPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && isEquityPoint(payload.point);
}

export function isWalletChartPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.sampled_at_ms)
    && Array.isArray(payload.points)
    && payload.points.length <= MAX_WALLET_TIMELINE_EVENTS
    && payload.points.every(isWalletChartPoint);
}

export function isWalletTimelinePayload(payload: Record<string, unknown>): boolean {
  if (!isRecord(payload.trade) || !isWalletChartPoint(payload.point)) return false;
  const trade = payload.trade;
  if (!isWalletTrade(trade)) return false;
  if (payload.outcome !== null && !isDispatchOutcome(payload.outcome)) return false;
  return walletChartPointMatchesTrade(
    payload.point,
    trade,
    payload.outcome === null ? null : payload.outcome.accepted
  );
}

export function isStreamHealthPayload(payload: Record<string, unknown>): boolean {
  return isNonnegativeInteger(payload.queue_depth)
    && isNonnegativeInteger(payload.peak_queue_depth)
    && (payload.book_dispatch_lag_ms === null
      || isNonnegativeInteger(payload.book_dispatch_lag_ms))
    && typeof payload.book_stale === 'boolean'
    && isNonnegativeInteger(payload.book_received_count)
    && isNonnegativeInteger(payload.book_coalesced_count);
}

function isMarketPoint(value: unknown): boolean {
  return isRecord(value)
    && isNonemptyString(value.token_id)
    && isNonemptyString(value.label)
    && isChartValueStatus(value.value, value.status)
    && Array.isArray(value.markers)
    && value.markers.every(isSide);
}

function isEquityPoint(value: unknown): boolean {
  return isRecord(value) && isChartValueStatus(value.value, value.status);
}

function isWalletChartPoint(value: unknown): value is Record<string, unknown> {
  return isRecord(value)
    && isNonemptyString(value.source_key)
    && isNonemptyString(value.wallet)
    && isNonnegativeInteger(value.trade_timestamp_ms)
    && isSide(value.side)
    && isNonnegativeDecimal(value.notional)
    && isNonemptyString(value.market_label)
    && (value.accepted === null || typeof value.accepted === 'boolean');
}

function isWalletTrade(
  trade: Record<string, unknown>
): trade is ValidWalletTrade {
  return isNonemptyString(trade.wallet)
    && isNonemptyString(trade.condition_id)
    && isNonemptyString(trade.token_id)
    && isSide(trade.side)
    && isPositiveDecimal(trade.size)
    && isOutcomePrice(trade.price)
    && isNonemptyString(trade.source_id)
    && !trade.source_id.includes(WALLET_SOURCE_KEY_SEPARATOR)
    && (trade.market_slug === undefined
      || trade.market_slug === null
      || typeof trade.market_slug === 'string')
    && (trade.outcome === undefined
      || trade.outcome === null
      || typeof trade.outcome === 'string')
    && isNonnegativeInteger(trade.trade_timestamp_ms)
    && isNonnegativeInteger(trade.observed_at_ms)
    && trade.observed_at_ms >= trade.trade_timestamp_ms;
}

function walletChartPointMatchesTrade(
  point: Record<string, unknown>,
  trade: ValidWalletTrade,
  accepted: boolean | null
): boolean {
  return point.source_key
      === `${trade.wallet.toLowerCase()}${WALLET_SOURCE_KEY_SEPARATOR}${trade.source_id}`
    && point.wallet === trade.wallet.toLowerCase()
    && point.trade_timestamp_ms === trade.trade_timestamp_ms
    && point.side === trade.side
    && new Decimal(String(point.notional)).eq(
      new Decimal(trade.price).mul(trade.size)
    )
    && point.market_label === walletMarketLabel(trade)
    && point.accepted === accepted;
}

function walletMarketLabel(trade: ValidWalletTrade): string {
  const { walletMarketLabelPolicy: policy } = runtimeContract.dashboard;
  if (trade.market_slug && trade.outcome) {
    return `${trade.market_slug}${policy.partSeparator}${trade.outcome}`;
  }
  if (trade.market_slug || trade.outcome) return trade.market_slug || trade.outcome || '';
  if (trade.token_id.length <= policy.maximumTokenLength) return trade.token_id;
  return `${trade.token_id.slice(0, policy.prefixLength)}${policy.ellipsis}`
    + trade.token_id.slice(-policy.suffixLength);
}

function isDispatchOutcome(value: unknown): value is Record<string, unknown> & { accepted: boolean } {
  if (!isRecord(value) || typeof value.accepted !== 'boolean') return false;
  return value.accepted
    ? runtimeContract.dispatchOutcome.acceptedAllowsSkipReason
      || value.skip_reason === null || value.skip_reason === undefined
    : !runtimeContract.dispatchOutcome.skippedRequiresSkipReason
      || DISPATCH_SKIP_REASONS.has(value.skip_reason as DispatchSkipReason);
}

function isChartValueStatus(value: unknown, status: unknown): boolean {
  if (typeof status !== 'string') return false;
  if (runtimeContract.chartValueStatus.nullValue.includes(status)) {
    return value === null;
  }
  return runtimeContract.chartValueStatus.valueRequired.includes(status)
    && isDecimal(value);
}
